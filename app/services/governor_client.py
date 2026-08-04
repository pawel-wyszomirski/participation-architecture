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

# Arbitrum One core governor - taken from the govId in alt.gov.arbitrum.foundation URLs
GOVERNOR_ADDRESS = "0xf07DeD9dC292157749B6Fd268E37DF6EA38395B9"
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
        """Proposals this delegate voted on, newest first.

        `days` bounds the scan. The DFI context window is far shorter, but a wider
        history keeps the novelty component meaningful.
        """
        voter_topic = "0x" + "0" * 24 + address[2:].lower()
        async with httpx.AsyncClient() as client:
            try:
                head = await self._block_number(client)
            except Exception as e:  # noqa: BLE001
                print(f"❌ Governor RPC unreachable: {e}")
                return []
            first = max(0, head - days * BLOCKS_PER_DAY)

            try:
                vote_logs = await self._logs(
                    client, [TOPIC_VOTE_CAST, voter_topic], first, head)
            except Exception as e:  # noqa: BLE001
                print(f"❌ Governor VoteCast scan failed: {e}")
                return []
            if not vote_logs:
                return []
            vote_logs = vote_logs[-limit:]

            voted_ids = {_word(log["data"], 0) for log in vote_logs}
            try:
                created = await self._logs(
                    client, [TOPIC_PROPOSAL_CREATED], first, head)
            except Exception as e:  # noqa: BLE001
                print(f"⚠ Governor ProposalCreated scan failed: {e}")
                created = []
            # Keep the full description, not just the title: the contract event
            # carries the complete proposal text (13k-21k characters for the AIPs
            # measured on 2026-08-03), which is what the reading_time component
            # needs. Without it that component silently scores zero for every
            # on-chain vote.
            meta: Dict[int, tuple] = {}
            for log in created:
                pid = _word(log["data"], 0)
                if pid in voted_ids:
                    description = _string_at(log["data"], 8)
                    meta[pid] = (_title_from_description(description), description)

            out: List[Proposal] = []
            times: Dict[str, int] = {}
            for log in vote_logs:
                pid = _word(log["data"], 0)
                block_hex = log["blockNumber"]
                if block_hex not in times:
                    times[block_hex] = await self._block_time(client, block_hex)
                title, body = meta.get(
                    pid, ("(proposal created before scan window)", ""))
                # Prefix keeps ids from colliding with Tally and Snapshot on merge.
                prop = Proposal(
                    id=f"governor:{pid}",
                    title=title,
                    body=body,
                    state="closed",
                    start=times[block_hex],
                )
                prop.voted_at = times[block_hex]
                prop.source = "governor"
                out.append(prop)
            out.sort(key=lambda p: p.voted_at or 0, reverse=True)
            return out


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
