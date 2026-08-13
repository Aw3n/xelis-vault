# XELIS Vault — Miner Economics & Delegation v10.8

> **Date :** 13 août 2026
> **Version :** v10.8
> **Objectif :** Expliquer le système de rewards miners, la délégation, et les scénarios de distribution

---

## 1. Distribution annuelle des rewards

**Budget total :** 5,500,000 VLT sur 10 ans = **550,000 VLT/an**

### Scénarios selon le nombre de miners

| Miners | VLT/miner/an | VLT/miner/jour | Total distribué/an | % du budget | Budget dure |
|--------|-------------|----------------|-------------------|-------------|-------------|
| 10 | 1,825 | 5 (cap) | 18,250 | 3.3% | 300+ ans |
| 25 | 1,825 | 5 (cap) | 45,625 | 8.3% | 120 ans |
| 50 | 1,825 | 5 (cap) | 91,250 | 16.6% | 60 ans |
| 100 | 1,825 | 5 (cap) | 182,500 | 33.2% | 30 ans |
| 250 | 1,825 | 5 (cap) | 456,250 | 83.0% | 12 ans |
| 500 | 1,100 | 3.0 | 550,000 | 100% | 10 ans |
| 1000 | 550 | 1.5 | 550,000 | 100% | 10 ans |

**Lecture :**
- **10-250 miners** : le cap quotidien de 5 VLT/jour limite les rewards. Le budget dure plus longtemps que prévu (soutenable).
- **500+ miners** : le cap n'est plus atteint, rewards proportionnels. Budget dure exactement 10 ans.
- **1000 miners** : rewards baissent naturellement (1.5 VLT/jour), APY diminue.

---

## 2. Système de délégation (MinerDelegation.slx)

### Principe

Les holders de VLT qui ne veulent pas faire tourner de miner peuvent **déléguer leur VLT à un miner de confiance**. Le miner gagne plus de rewards (stake plus élevé), prend une commission, et le délégateur gagne du yield passif.

### Flow

```
1. Miner Alice s'enregistre :
   - Nom : "AliceOracle"
   - Commission : 10% (1000 bps)
   - Own stake : 1,000 VLT

2. Bob délègue 5,000 VLT à Alice :
   - Alice total stake = 1,000 + 5,000 = 6,000 VLT
   - Bob devient délégateur d'Alice

3. Alice gagne 5 VLT de reward (cap quotidien) :
   - Own share : (1,000 / 6,000) × 5 = 0.83 VLT
   - Delegated pool : (5,000 / 6,000) × 5 = 4.17 VLT
   - Commission (10%) : 0.42 VLT → Alice
   - Delegator actual : 3.75 VLT → Bob (proportionnel à ses 5,000 VLT)

4. Alice reçoit : 0.83 + 0.42 = 1.25 VLT
   Bob reçoit : 3.75 VLT (claim quand il veut)

5. Si Alice est slaschée (ex: 10% de son stake) :
   - Slashing = 600 VLT (10% de 6,000)
   - Alice own stake : 1,000 - 100 = 900 VLT (10% de son own)
   - Bob delegated : 5,000 - 500 = 4,500 VLT (10% de son délégué)
   - Les délégateurs partagent le risque proportionnellement
```

### Sécurité oracle

**Pourquoi la délégation ne casse pas l'oracle :**

1. **Cap quotidien** : Un miner avec 100,000 VLT délégués gagne toujours max 5 VLT/jour. Pas d'incitation à accumuler trop de délégation.

2. **min_providers dans StakedOracle** : Même si un miner a 50% du stake total, l'oracle requiert min 3 (ou 10 en mode normal) providers indépendants. Un seul miner ne peut pas manipuler le prix.

3. **Médiane, pas moyenne** : L'oracle prend la médiane des prix soumis. Un miner malhonnête avec beaucoup de stake ne peut pas déplacer la médiane seul.

4. **Slashing progressif** : Si un miner soumet un prix faux, il est slasché (1% à 50% du stake). Les délégateurs partagent la perte → ils ont intérêt à choisir un miner fiable.

5. **Undelegate delay** : 7 jours pour unstake. Empêche les délégateurs de fuir immédiatement si leur miner est suspect.

### Anti-concentration

- **Max 500 délégateurs par miner** — empêche un miner de capturer tout le stake
- **Cap quotidien 5 VLT** — un miner avec énormément de stake ne gagne pas plus
- **min_providers oracle** — nécessite plusieurs miners indépendants

---

## 3. Rewards selon stake (avec délégation)

### Tableau stake vs reward

| Miner own stake | Délégué | Total stake | Reward/jour | APY (own) | APY (délégateur) |
|-----------------|---------|-------------|-------------|-----------|-------------------|
| 1,000 VLT | 0 | 1,000 | 5 VLT (cap) | 182% | — |
| 1,000 VLT | 4,000 | 5,000 | 5 VLT (cap) | 36% | 5.5% |
| 1,000 VLT | 9,000 | 10,000 | 5 VLT (cap) | 18% | 4.1% |
| 1,000 VLT | 99,000 | 100,000 | 5 VLT (cap) | 1.8% | 0.4% |

**Lecture :**
- **Miner seul (1,000 VLT)** : 182% APY (attractif pour bootstrap)
- **Miner avec délégation** : APY diminue mais volume augmente
- **Délégateur** : 4-5% APY passif (correct pour du staking)

### Pourquoi le cap de 5 VLT/jour est essentiel

Sans cap, un miner avec 100,000 VLT délégués gagnerait 100x plus qu'un miner avec 1,000 VLT. Ça créerait une concentration dangereuse. Le cap :
- Garantit que tous les miners actifs gagnent la même chose (5 VLT/jour max)
- Encourage la **diversité** des miners plutôt que la concentration
- Les délégateurs répartissent leur stake sur plusieurs miners (meilleure sécurité)

---

## 4. Mécanique de slashing avec délégation

### Scénarios de slashing

| Sévérité | % stake slasché | Miner own (1,000 VLT) | Délégateur (5,000 VLT) |
|----------|-----------------|----------------------|------------------------|
| 0 (outlier) | 1% | -10 VLT | -50 VLT |
| 1 (late) | 5% | -50 VLT | -250 VLT |
| 2 (offline) | 10% | -100 VLT | -500 VLT |
| 3 (censorship) | 25% | -250 VLT | -1,250 VLT |
| 4 (malicious) | 50% | -500 VLT | -2,500 VLT |

**Pourquoi les délégateurs partagent le risque :**
- Si le miner fait n'importe quoi, les délégateurs perdent aussi
- Ça les incite à **surveiller** leur miner et à unstake s'il devient suspect
- Marché libre : les bons miners attirent plus de délégation, les mauvais perdent

---

## 5. Comment choisir un miner (pour les délégateurs)

### Critères de sélection

| Critère | Où vérifier | Bon signe |
|---------|-------------|-----------|
| **Réputation** | `get_miner_profile()` | > 8000 (Excellent) |
| **Total slashed** | `get_miner_profile()` | Faible ou 0 |
| **Commission** | `get_miner_profile()` | 5-15% (raisonnable) |
| **Delegator count** | `get_miner_profile()` | 10-100 (ni trop peu, ni trop) |
| **Uptime** | XelisVaultMiner | Heartbeats réguliers |
| **Valid submissions %** | XelisVaultMiner | > 95% |

### Risques pour le délégateur

1. **Slashing** : Si le miner est slasché, le délégateur perd proportionnellement
2. **Downtime** : Si le miner est offline, pas de rewards (mais pas de slashing non plus)
3. **Commission change** : Le miner peut changer sa commission (mais max 20%)
4. **Undelegate delay** : 7 jours pour récupérer son VLT

---

## 6. Intégration avec XelisVaultMiner

### Modifications nécessaires dans XelisVaultMiner

Quand `distribute_reward()` est appelé, au lieu de minter directement au miner :

1. Vérifier si le miner a un profil de délégation
2. Si oui, appeler `MinerDelegation.distribute_rewards(miner_addr, reward)`
3. Si non, minter directement au miner (comportement actuel)

Quand `slash_miner()` est appelé :

1. Slasher le own stake dans XelisVaultMiner
2. Appeler `MinerDelegation.apply_slashing(miner_addr, slash_amount)` pour propager aux délégateurs

### Nouveaux entry wrappers nécessaires

- `XelisVaultMiner.get_miner_own_stake(addr)` — pour que MinerDelegation connaisse le own stake
- `XelisVaultMiner.set_delegation_contract(hash)` — pour configurer le contrat de délégation

---

## 7. Exemples concrets

### Scénario 1 : Bootstrap (10 miners, pas de délégation)

```
10 miners, chacun avec 1,000 VLT own stake
Budget : 550,000 VLT/an
Par miner : 1,825 VLT/an (5 VLT/jour, cap atteint)
APY : 182%
ROI : 200 jours
```

### Scénario 2 : Croissance (100 miners, délégation modérée)

```
100 miners, chacun avec 1,000 VLT own + 4,000 VLT délégué (4 délégateurs)
Total stake par miner : 5,000 VLT
Budget : 550,000 VLT/an
Par miner : 1,825 VLT/an (5 VLT/jour, cap)
  - Own share : 365 VLT/an (20%)
  - Commission (10%) : 146 VLT/an
  - Miner total : 511 VLT/an (APY 51% sur own stake)
  - Delegator : 1,314 VLT/an pour 4,000 VLT (APY 33% chacun... wait, c'est 4 délégateurs)
  
En fait : 4 délégateurs × 1,000 VLT chacun = 4,000 VLT
  - Delegator pool : 1,460 VLT/an pour 4,000 VLT
  - Commission 10% : 146 VLT → miner
  - Delegator actual : 1,314 VLT/an pour 4,000 VLT
  - Par délégateur : 328 VLT/an pour 1,000 VLT = 33% APY
```

### Scénario 3 : Maturité (500 miners, délégation importante)

```
500 miners, chacun avec 1,000 VLT own + 9,000 VLT délégué
Total stake par miner : 10,000 VLT
Budget : 550,000 VLT/an
Par miner : 1,100 VLT/an (3 VLT/jour, cap non atteint)
  - Own share : 110 VLT/an (10%)
  - Commission (10%) : 99 VLT/an
  - Miner total : 209 VLT/an (APY 21% sur own)
  - Delegator : 891 VLT/an pour 9,000 VLT = 9.9% APY
```

### Scénario 4 : Saturation (1000 miners)

```
1000 miners, chacun avec 1,000 VLT own + 4,000 VLT délégué
Total stake par miner : 5,000 VLT
Budget : 550,000 VLT/an
Par miner : 550 VLT/an (1.5 VLT/jour)
  - Own share : 110 VLT/an (20%)
  - Commission (10%) : 44 VLT/an
  - Miner total : 154 VLT/an (APY 15% sur own)
  - Delegator : 396 VLT/an pour 4,000 VLT = 9.9% APY
```

---

## 8. Conclusion

Le système de délégation crée un **marché de la sécurité** :
- **Miners** compétitent pour attirer des délégateurs (bonne réputation, commission raisonnable)
- **Délégateurs** choisissent les meilleurs miners (yield + risque de slashing)
- **Protocole** bénéficie de plus de stake total = attaque plus chère

**Le cap quotidien de 5 VLT** est essentiel pour :
- Empêcher la concentration (un miner avec 100k VLT ne gagne pas plus qu'un avec 1k)
- Garantir la soutenabilité (budget dure 10+ ans)
- Encourager la diversité des miners

**L'anti-Sybil** fonctionne car :
- Min stake 1,000 VLT (10x plus qu'avant)
- ROI > 200 jours (skin in the game réel)
- Slashing progressif (jusqu'à 50% du stake)
- Délégateurs partagent le risque (surveillance naturelle)

---

*XELIS Vault — Miner Economics & Delegation v10.8*
