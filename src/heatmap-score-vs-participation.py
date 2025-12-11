# @title 📊 Generowanie Heatmapy: Fatigue Score vs Participation Rate
# @markdown Uruchom ten komórkę, aby wygenerować wykres.

import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
import io

# 1. Dane wejściowe (na podstawie Twojego pliku whales_burnout.csv)
# Wkleiłem fragment danych jako string dla demonstracji.
# W pełnej wersji możesz załadować plik: df = pd.read_csv('whales_burnout.csv')
csv_data = """delegate,name,avg_voting_power,fatigue_score,trend,participation_30d,burnout_detected
0xb4c0,Entropy Advisors,19032218,55.0,declining,0.25,FALSE
0x7a45,LobbyFi,16163069,100.0,declining,0.0,TRUE
0x1B68,,16077953,54.0,declining,0.5,FALSE
0x11cd,,14754884,54.0,declining,0.5,FALSE
0xB933,,12158461,58.0,declining,0.5,FALSE
0x2ef2,,11251066,91.0,declining,0.25,FALSE
0xF4B0,,10668715,57.0,declining,0.75,FALSE
0x5672,,10032832,100.0,declining,0.0,FALSE
0x5663,,9734693,100.0,declining,0.25,TRUE
0xA5dF,,9355999,54.0,declining,0.0,FALSE
0x2e3B,,8522924,53.0,declining,0.5,FALSE
0x183D,,8002977,54.0,declining,0.5,FALSE
0xF92F,,7635084,100.0,declining,0.25,TRUE
0xdb57,,6752890,83.0,declining,0.0,FALSE
0x8F73,,6339336,96.0,stable,0.0,FALSE
0xb5B0,,5935399,55.0,declining,0.25,FALSE
0x8b37,,5226915,67.0,declining,0.5,FALSE
0x4fD8,,5115646,54.0,declining,0.5,FALSE
0x0eB5,,4178604,100.0,stable,0.5,FALSE
0x0edB,,4166292,54.0,declining,0.5,FALSE
0xa6e8,,3835298,100.0,declining,0.25,TRUE
0x8393,,3631018,54.0,declining,0.5,FALSE
0x79C4,,3516790,100.0,stable,0.25,FALSE
0xd333,,3294643,68.0,declining,0.5,FALSE
0xb29A,,3215194,55.0,declining,0.5,FALSE
0x3070,,3096136,100.0,stable,0.25,FALSE
0xa9e7,,2754908,54.0,declining,0.0,FALSE
0xAbAb,,2699880,100.0,declining,0.25,TRUE
0xBA87,,2372514,100.0,stable,0.0,FALSE
0x9cea,,2000010,68.0,declining,0.0,FALSE
0x583E,,1987202,56.0,declining,0.5,FALSE
0x18BF,,1954114,100.0,declining,0.0,TRUE
0x8326,,1365336,54.0,declining,0.5,FALSE
0x7B0b,,1294286,100.0,stable,0.5,FALSE
0xBbE9,,1176378,100.0,declining,0.0,FALSE
0x5396,,841026,53.0,declining,0.5,FALSE
0x5a35,,792627,98.0,declining,0.0,TRUE
0x4F68,,759122,82.0,declining,0.75,FALSE
0xaE79,,743105,100.0,stable,0.0,FALSE
0x9D64,,602027,54.0,declining,0.0,FALSE
0xA786,,600347,100.0,declining,0.0,FALSE
0x13BD,,514168,68.0,declining,0.0,FALSE
0x3D18,,373415,100.0,declining,0.0,TRUE
0x010D,,351351,100.0,declining,0.25,TRUE
0x5162,,319116,56.0,declining,0.5,FALSE
0xf955,,271099,100.0,declining,0.0,TRUE
0xE93D,,242889,61.0,declining,0.5,FALSE
0xb356,,227021,54.0,declining,0.5,FALSE
0xE594,,225867,53.0,declining,0.25,FALSE
0x714D,,212118,55.0,declining,0.25,FALSE
0x2D7d,,198104,74.0,declining,0.75,FALSE
0xea17,,185182,53.0,declining,0.5,FALSE
0xfA01,,172709,90.0,declining,0.5,FALSE
0xa0BF,,159865,100.0,declining,0.0,FALSE
0xC0C3,,154390,100.0,declining,0.0,TRUE
0xCE8A,,150008,100.0,declining,0.0,TRUE
0x43D3,,126158,100.0,declining,0.0,TRUE
0x3EF1,,119497,58.0,declining,0.5,FALSE
0xAfD5,,112433,56.0,declining,0.0,FALSE
0x6f9B,,109930,100.0,declining,1.0,FALSE
0x0703,,103945,100.0,declining,0.25,TRUE
0x4D6C,,100301,100.0,declining,0.25,TRUE"""

# Wczytanie danych do DataFrame
df = pd.read_csv(io.StringIO(csv_data))

# 2. Konfiguracja Heatmapy
# Tworzymy koszyki (bins) dla osi X i Y
# Participation (Output) - co 10% (0.1)
# Fatigue (Time Cost) - co 10 punktów

x_bins = [0, 0.2, 0.4, 0.6, 0.8, 1.0]
x_labels = ['0-20%', '20-40%', '40-60%', '60-80%', '80-100%']

y_bins = [0, 20, 40, 60, 80, 100]
y_labels = ['0-20 (Low)', '21-40', '41-60', '61-80', '81-100 (High)']

df['Participation_Bin'] = pd.cut(df['participation_30d'], bins=x_bins, labels=x_labels, include_lowest=True)
df['Fatigue_Bin'] = pd.cut(df['fatigue_score'], bins=y_bins, labels=y_labels, include_lowest=True)

# Tworzenie macierzy do heatmapy (liczebność delegatów w każdym segmencie)
heatmap_data = df.groupby(['Fatigue_Bin', 'Participation_Bin'], observed=False).size().unstack()

# Odwracamy oś Y, aby wysokie zmęczenie było na górze
heatmap_data = heatmap_data.iloc[::-1]

# 3. Rysowanie wykresu
plt.figure(figsize=(10, 8))
sns.set(style="whitegrid")

# Używamy palety kolorów 'Reds' lub 'YlOrRd' aby pokazać intensywność ("danger zones")
ax = sns.heatmap(heatmap_data, annot=True, fmt='d', cmap='YlOrRd', 
                 linewidths=.5, cbar_kws={'label': 'Number of Delegates'})

# Tytuły i etykiety
plt.title('Delegate Health Matrix: Time-Cost vs Voting Output\n(Arbitrum DAO Sample)', fontsize=16, pad=20)
plt.xlabel('Voting Output (Participation Rate 30d)', fontsize=12)
plt.ylabel('Human Time-Cost (Fatigue Score)', fontsize=12)

# Oznaczenie strefy ryzyka
# Dodajemy tekstowy komentarz na wykresie
plt.text(3.5, 0.5, '⚠️ BURNOUT ZONE\nHigh Output / High Cost', 
         horizontalalignment='center', verticalalignment='center', 
         color='black', weight='bold', fontsize=10,
         bbox=dict(facecolor='white', alpha=0.8, edgecolor='red'))

plt.text(0.5, 4.5, '💤 PASSIVE\nLow Output / Low Cost', 
         horizontalalignment='center', verticalalignment='center', 
         color='black', weight='bold', fontsize=10,
         bbox=dict(facecolor='white', alpha=0.8, edgecolor='green'))

plt.tight_layout()
plt.show()

# 4. Wyświetlenie statystyk "Burnout Zone"
burnout_zone = df[(df['fatigue_score'] > 80) & (df['participation_30d'] > 0.6)]
print(f"\n🚨 Delegates in the Burnout Zone (Fatigue > 80 & Participation > 60%): {len(burnout_zone)}")
if not burnout_zone.empty:
    print(burnout_zone[['delegate', 'fatigue_score', 'participation_30d']].to_string(index=False))
