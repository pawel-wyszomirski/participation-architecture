"""On-chain votes read straight from the Arbitrum Governor contract.

<!-- catalog-read --> checked app/services: only snapshot_client and tally_client
exist; neither reads the chain directly.

Why this exists
---------------
Tally stopped indexing Arbitrum. The last on-chain proposal it reports is from
2026-06-08, while the governance contract kept producing proposals after that
date. Arbitrum moved its voting UI to `alt.gov.arbitrum.foundation`, which reads
the contract directly - the proposal URL carries `govId=eip155:42161:0xf07DeD...`.

The failure was silent: Tally answers HTTP 200 with a frozen dataset, so a health
check that only asks "does the API respond" cannot tell fresh data from stale.
A delegate reported his most recent vote and neither Tally nor Snapshot had it.

Reading the chain removes the intermediary. Contracts do not rebrand, get
deprecated behind a redirect, or quietly stop indexing one DAO.

Contract interface
------------------
Standard OpenZeppelin Governor events:

    ProposalCreated(uint256 proposalId, address proposer, address[] targets,
                    uint256[] values, string[] signatures, bytes[] calldatas,
                    uint256 startBlock, uint256 endBlock, string description)
    VoteCast(address indexed voter, uint256 proposalId, uint8 support,
             uint256 weight, string reason)

Only `voter` is indexed, so votes filter by topic while proposal ids come from
decoding the data payload.

Returns `Proposal` instances with `.voted_at` and `.source="governor"`, matching
`tally_client` and `snapshot_client` so the merge in `main.py` needs no change.
"""
from __future__ import annotations

import asyncio
from typing import Dict, List, Optional

import httpx

from app.services.snapshot_client import Proposal
from app.services.fatigue_engine import (
    SourceReceipt, HEALTHY_COMPLETE, HEALTHY_EMPTY, PARTIAL, TRUNCATED,
    UNAVAILABLE, ERROR,
)

# Arbitrum One runs TWO governors and a delegate's workload spans both.
#
# The core address comes from the govId in alt.gov.arbitrum.foundation URLs. The
# treasury address was not guessed: an unfiltered getLogs scan for
# ProposalCreated around a known treasury proposal (Continued Funding for the
# Arbitrum Foundation, 2026-06-08 16:52 UTC) returned exactly one event, emitted
# by 0x789f. Reading the address off the chain that produced the proposal beats
# copying it from documentation that can go stale the way Tally's index did.
#
# Why both matter (2026-08-05): arbdata.com lists 89 proposals - 31 core and
# 58 treasury. Scanning core alone left two thirds of the DAO's business outside
# the measurement, so a delegate voting on treasury matters carried load the
# index could not see. That is a coverage defect, distinct from the look-ahead
# and the missing end timestamp: those corrupted events we could see, this one
# removed events from view.
GOVERNORS = {
    "core": "0xf07DeD9dC292157749B6Fd268E37DF6EA38395B9",
    "treasury": "0x789fC99093B09aD01C34DC7251D0C89ce743e5a4",
}
GOVERNOR_ADDRESS = GOVERNORS["core"]  # zgodność wsteczna
CHAIN_ID = 42161

# Public endpoints, tried in order. Public RPCs answer 403 when a getLogs range is
# too wide, which is why the scan below walks the chain in windows.
RPC_ENDPOINTS = [
    "https://arbitrum-one.publicnode.com",
    "https://arb1.arbitrum.io/rpc",
    "https://arbitrum.llamarpc.com",
]

# keccak256 of the event signatures
TOPIC_VOTE_CAST = "0xb8e138887d0aa13bab447e82de9d5c1777041ecd21ca36ba824ff1e6c07ddda4"
TOPIC_PROPOSAL_CREATED = "0x7d84a6263ae0d98d3329bd7b46bb4e8d6f98cd35a7adb45c274c8b7fd5ebd5e0"

# Arbitrum One produces roughly 4 blocks per second.
BLOCKS_PER_DAY = 4 * 60 * 60 * 24
# Window size for a single getLogs call. Wider ranges get refused by public nodes.
SCAN_WINDOW_BLOCKS = BLOCKS_PER_DAY * 3

# `startBlock` and `endBlock` in ProposalCreated are ETHEREUM (L1) block numbers,
# not Arbitrum ones - Arbitrum's `block.number` returns the L1 height. Measured on
# this contract: an event emitted at L2 block 483_508_532 carries startBlock
# 25_547_165, and the two orders of magnitude are the giveaway. Converting them
# with an Arbitrum RPC would therefore read a completely unrelated block, so the
# window is reconstructed arithmetically instead.
#
# 12 s is the post-merge Ethereum slot time. Confirmed twice against live data:
# two proposals 13.86 days apart differ by 99_483 blocks (12.04 s/block), and
# `endBlock - startBlock` equals `votingPeriod()` = 100_800 blocks = exactly
# 14 days at 12 s. Drift over a full voting period is on the order of hours,
# which concurrency - a count of overlapping decisions - tolerates.
L1_BLOCK_SECONDS = 12

# Function selectors on the standard OpenZeppelin Governor interface.
SELECTOR_VOTING_DELAY = "0x3932abb1"   # votingDelay()
# Fallback if the contract cannot be queried. Current on-chain value; governance
# can change it, which is why the live call comes first and this is only a floor.
DEFAULT_VOTING_DELAY_BLOCKS = 21_600


def _word(data: str, index: int) -> int:
    """Read the n-th 32-byte word of an ABI payload as an integer."""
    raw = data[2:] if data.startswith("0x") else data
    start = index * 64
    chunk = raw[start:start + 64]
    return int(chunk, 16) if chunk else 0


def _string_at(data: str, offset_word: int) -> str:
    """Decode a dynamically sized string given the word holding its offset."""
    raw = data[2:] if data.startswith("0x") else data
    try:
        offset = _word(data, offset_word) * 2
        length = int(raw[offset:offset + 64], 16) * 2
        body = raw[offset + 64: offset + 64 + length]
        return bytes.fromhex(body).decode("utf-8", "replace")
    except Exception:  # noqa: BLE001 - malformed payload must not kill the scan
        return ""


def _title_from_description(description: str) -> str:
    """First non-empty line of the proposal description, markdown heading stripped."""
    for line in description.splitlines():
        line = line.strip().lstrip("#").strip()
        if line:
            return line[:200]
    return "(untitled proposal)"


class GovernorClient:
    """Reads proposals and votes from the governance contract."""

    def __init__(self, address: str = GOVERNOR_ADDRESS,
                 endpoints: Optional[List[str]] = None):
        self.address = address
        self.endpoints = endpoints or RPC_ENDPOINTS
        self._endpoint: Optional[str] = None

    async def _call(self, client: httpx.AsyncClient, method: str, params: list) -> dict:
        """One JSON-RPC call, falling back through endpoints on transport errors.

        A node that refuses the request (403, 429) is a different problem from a
        node that answers "no such data" - the first must not be read as an empty
        result, or the scan silently reports an active delegate as inactive.
        """
        last_error = None
        order = ([self._endpoint] if self._endpoint else []) + \
                [e for e in self.endpoints if e != self._endpoint]
        for url in order:
            try:
                r = await client.post(
                    url,
                    json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
                    headers={"Content-Type": "application/json"},
                    timeout=45.0,
                )
                if r.status_code >= 400:
                    last_error = f"HTTP {r.status_code} from {url}"
                    continue
                payload = r.json()
                if "error" in payload:
                    last_error = f"{payload['error']} from {url}"
                    continue
                self._endpoint = url
                return payload
            except Exception as e:  # noqa: BLE001
                last_error = f"{type(e).__name__}: {e} ({url})"
        raise RuntimeError(f"all RPC endpoints failed - {last_error}")

    async def _block_number(self, client: httpx.AsyncClient) -> int:
        return int((await self._call(client, "eth_blockNumber", []))["result"], 16)

    async def _block_time(self, client: httpx.AsyncClient, block_hex: str) -> int:
        blk = (await self._call(client, "eth_getBlockByNumber", [block_hex, False]))["result"]
        return int(blk["timestamp"], 16)

    async def _voting_delay(self, client: httpx.AsyncClient) -> int:
        """Blocks between a proposal being created and voting opening.

        Asked of the contract rather than hardcoded, because governance can change
        it. A failure falls back to the current value instead of aborting - a
        slightly wrong window beats no window at all, and no window means the
        concurrency component silently scores zero for every on-chain vote.
        """
        try:
            res = await self._call(client, "eth_call", [
                {"to": self.address, "data": SELECTOR_VOTING_DELAY}, "latest"])
            raw = res.get("result")
            if raw and raw != "0x":
                return int(raw, 16)
        except Exception as e:  # noqa: BLE001
            print(f"⚠ Governor votingDelay() unreadable, using default: {e}")
        return DEFAULT_VOTING_DELAY_BLOCKS

    async def _logs(self, client: httpx.AsyncClient, topics: list,
                    from_block: int, to_block: int) -> List[dict]:
        """getLogs over a block range, split into windows the public nodes accept."""
        out: List[dict] = []
        start = from_block
        while start <= to_block:
            end = min(start + SCAN_WINDOW_BLOCKS, to_block)
            res = await self._call(client, "eth_getLogs", [{
                "address": self.address,
                "topics": topics,
                "fromBlock": hex(start),
                "toBlock": hex(end),
            }])
            out.extend(res.get("result") or [])
            start = end + 1
        return out

    async def fetch_voted_proposals(self, address: str, days: int = 120,
                                    limit: int = 200) -> List[Proposal]:
        """Proposals this delegate voted on across BOTH governors, newest first.

        `days` bounds the scan. The DFI context window is far shorter, but a wider
        history keeps the novelty component meaningful.

        Scanning both contracts is the point: two thirds of Arbitrum's proposals
        live on the treasury governor, and a workload measure that reads one
        contract reports a delegate as idle while they were voting.
        """
        out, _ = await self.fetch_voted_observations(address, days=days, limit=limit)
        return out

    async def fetch_voted_observations(self, address: str, days: int = 120,
                                       limit: int = 200
                                       ) -> "tuple[List[Proposal], SourceReceipt]":
        """`fetch_voted_proposals` plus ONE capability receipt for both
        governors (closure review point 2). The worst state wins: an RPC that
        does not answer for either contract makes the whole source
        UNAVAILABLE, because a delegate's on-chain history is the union of both
        and half of it cannot be called complete.

            UNAVAILABLE  - RPC unreachable for a contract
            ERROR        - VoteCast scan refused (getLogs error)
            TRUNCATED    - more VoteCast logs than `limit`; oldest dropped
            PARTIAL      - some votes lack a voting window (ProposalCreated
                           outside the scan, or the ProposalCreated scan failed)
            HEALTHY_*    - everything asked for came back

        Native identity (point 3): `source_vote_id` = transaction hash + log
        index of the VoteCast event, `native_proposal_id` = the uint256
        proposal id as the contract emitted it.
        """
        wszystkie: List[Proposal] = []
        stany: List[str] = []
        szczegoly: List[str] = []
        unknown_total = 0
        for rola, adres in GOVERNORS.items():
            klient = GovernorClient(address=adres, endpoints=self.endpoints)
            klient._endpoint = self._endpoint
            glosy, stan, szczegol, unknown = await klient._votes_on_one_governor(
                address, days, limit, rola)
            wszystkie.extend(glosy)
            stany.append(stan)
            unknown_total += unknown
            if szczegol:
                szczegoly.append(f"{rola}: {szczegol}")
        wszystkie.sort(key=lambda p: p.voted_at or 0, reverse=True)
        # Severity order: the worst state of the two contracts describes the source.
        ranking = [UNAVAILABLE, ERROR, TRUNCATED, PARTIAL, HEALTHY_COMPLETE, HEALTHY_EMPTY]
        stan = next((s for s in ranking if s in stany), HEALTHY_EMPTY)
        if stan == HEALTHY_EMPTY and wszystkie:
            stan = HEALTHY_COMPLETE
        return wszystkie, SourceReceipt("governor", stan, events=len(wszystkie),
                                        unknown_window=unknown_total, limit=limit,
                                        detail="; ".join(szczegoly))

    async def _votes_on_one_governor(self, address: str, days: int, limit: int,
                                     rola: str) -> "tuple[List[Proposal], str, str, int]":
        """Jeden kontrakt. Wydzielone z `fetch_voted_proposals`, bo skan chodzi
        teraz po dwóch, a każdy ma własne `votingDelay()` i własny zbiór zdarzeń.

        Zwraca (obserwacje, stan źródła, szczegół, liczba bez okna)."""
        voter_topic = "0x" + "0" * 24 + address[2:].lower()
        async with httpx.AsyncClient() as client:
            try:
                head = await self._block_number(client)
            except Exception as e:  # noqa: BLE001
                print(f"❌ Governor RPC unreachable: {e}")
                return [], UNAVAILABLE, f"RPC unreachable: {e}"[:200], 0
            first = max(0, head - days * BLOCKS_PER_DAY)

            try:
                vote_logs = await self._logs(
                    client, [TOPIC_VOTE_CAST, voter_topic], first, head)
            except Exception as e:  # noqa: BLE001
                print(f"❌ Governor VoteCast scan failed: {e}")
                return [], ERROR, f"VoteCast scan failed: {e}"[:200], 0
            if not vote_logs:
                return [], HEALTHY_EMPTY, "", 0
            truncated = len(vote_logs) > limit
            vote_logs = vote_logs[-limit:]

            voted_ids = {_word(log["data"], 0) for log in vote_logs}
            created_scan_failed = ""
            try:
                created = await self._logs(
                    client, [TOPIC_PROPOSAL_CREATED], first, head)
            except Exception as e:  # noqa: BLE001
                print(f"⚠ Governor ProposalCreated scan failed: {e}")
                created = []
                created_scan_failed = f"ProposalCreated scan failed: {e}"[:200]
            # Keep the full description, not just the title: the contract event
            # carries the complete proposal text (13k-21k characters for the AIPs
            # measured on 2026-08-03), which is what the reading_time component
            # needs. Without it that component silently scores zero for every
            # on-chain vote.
            times: Dict[str, int] = {}
            voting_delay = await self._voting_delay(client)

            # Real windows from the DAO's own proposal registry, where it covers
            # the proposal. The arithmetic below stays as the fallback: checked
            # against ArbOS61 it ends the vote two days early, and concurrency
            # counts overlaps, so two days move real numbers.
            from app.services.arbdata_client import ArbdataClient
            rejestr = ArbdataClient()
            await rejestr.load()

            # The voting window comes from the event too. Words 6 and 7 hold
            # startBlock and endBlock, and the creation timestamp anchors them:
            #
            #   opens  = created_at + votingDelay        * 12 s
            #   closes = opens      + (endBlock - startBlock) * 12 s
            #
            # The duration is read per proposal rather than from votingPeriod(),
            # so a proposal created under different governance parameters still
            # reconstructs correctly; only the delay uses the current value.
            meta: Dict[int, tuple] = {}
            for log in created:
                pid = _word(log["data"], 0)
                if pid not in voted_ids:
                    continue
                description = _string_at(log["data"], 8)
                block_hex = log["blockNumber"]
                if block_hex not in times:
                    times[block_hex] = await self._block_time(client, block_hex)
                created_at = times[block_hex]
                okno = rejestr.window(pid)
                if okno:
                    opens, closes = okno
                else:
                    span_blocks = _word(log["data"], 7) - _word(log["data"], 6)
                    opens = created_at + voting_delay * L1_BLOCK_SECONDS
                    closes = opens + max(span_blocks, 0) * L1_BLOCK_SECONDS
                meta[pid] = (_title_from_description(description), description,
                             opens, closes)

            out: List[Proposal] = []
            without_window = 0
            for log in vote_logs:
                pid = _word(log["data"], 0)
                block_hex = log["blockNumber"]
                if block_hex not in times:
                    times[block_hex] = await self._block_time(client, block_hex)
                voted_at = times[block_hex]
                if pid in meta:
                    title, body, opens, closes = meta[pid]
                else:
                    # ProposalCreated fell outside the scan window, so the real
                    # voting period is unknown. The vote timestamp is NOT a
                    # substitute: it would claim the proposal opened and closed
                    # the instant this delegate voted, and a different delegate
                    # voting on the same proposal would get a different window.
                    # Left unset so concurrency skips it - counted and reported
                    # below, because a silent skip reads as "nothing overlapped".
                    title, body = "(proposal created before scan window)", ""
                    opens, closes = voted_at, None
                    without_window += 1
                # Prefix keeps ids from colliding with Tally and Snapshot on merge.
                # The governor role goes in too: the same delegate can face a core
                # and a treasury proposal at once, and the two must stay distinct.
                prop = Proposal(
                    id=f"governor:{rola}:{pid}",
                    title=title,
                    body=body,
                    state="closed",
                    start=opens,
                )
                prop.end = closes
                prop.voted_at = voted_at
                prop.source = f"governor:{rola}"
                prop.source_domain = f"governor:{rola}"
                prop.source_vote_id = f"{log.get('transactionHash', '')}:{log.get('logIndex', '')}"
                prop.native_proposal_id = str(pid)
                prop.voter = address
                prop.cast_at = voted_at
                # Kategoria z taksonomii DAO - podstawa skladnika `novelty`.
                # Brak kategorii zostaje None, NIE pusty ciag: "nie wiemy, czego
                # dotyczy" to inna rzecz niz "nie nalezy do zadnej kategorii".
                przedmiot = rejestr.subject(pid)
                prop.category = przedmiot[0] if przedmiot and przedmiot[0] else None
                out.append(prop)
            if without_window:
                print(f"⚠ Governor[{rola}]: {without_window} of {len(out)} votes have no "
                      f"known voting window (proposal created before the "
                      f"{days}-day scan) - excluded from concurrency")
            out.sort(key=lambda p: p.voted_at or 0, reverse=True)
            if truncated:
                stan, szczegol = TRUNCATED, f"more than {limit} VoteCast logs, oldest dropped"
            elif without_window or created_scan_failed:
                stan = PARTIAL
                szczegol = created_scan_failed or (
                    f"{without_window} of {len(out)} votes without a known voting window")
            else:
                stan, szczegol = HEALTHY_COMPLETE, ""
            return out, stan, szczegol, without_window


async def _demo(address: str) -> None:
    votes = await GovernorClient().fetch_voted_proposals(address, days=90)
    print(f"{len(votes)} on-chain votes for {address}")
    import datetime as dt
    for p in votes[:10]:
        stamp = dt.datetime.fromtimestamp(p.voted_at, dt.timezone.utc)
        print(f"  {stamp:%Y-%m-%d %H:%M} | {p.title[:64]}")


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        raise SystemExit("usage: python -m app.services.governor_client <delegate address>")
    asyncio.run(_demo(sys.argv[1]))
