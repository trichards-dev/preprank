# LHSAA Power Rating — Inclusion Rules

> Source: [LHSAA 2023 Football Season Overview Bulletin](https://www.lhsaa.org/siteuploads/editorimg/file/Football/2023%20Football%20General%20Info%20Bulletin.pdf) — Section 14 (Power Rating), Section 6.12 (Reporting), Section 14.12.1–14.12.3 (Wild Card / Power Rating).
> Verified 2026-05-25 as part of Phase 0 cleanup-v2. Cross-source check (`scripts/audit/cross_source.py`) should model these rules explicitly.

## Formula (Section 14.12.1, 14.12.2)

For each team:

```
Power Rating = ( Σ game_score_for_team ) / total_regular_season_games × 10
             rounded to nearest 0.01

where game_score_for_team =
    (result_of_contest)                          # 10=W, 5=T, 0=L
  + (play_up_points)                             # +2 per division higher
  + (opponent_strength)                          # opp_wins / opp_games × 10
  + (special_case_adjustments)                   # double-forfeit, tie-OOS
```

**Result-of-contest values (per 14.12.1):**

| Result | Same Div | Higher Div opp | Lower Div opp |
|---|---|---|---|
| Win | 10 | 10 + 2 × (div_diff) | 10 |
| Loss | 0 | 0 + 2 × (div_diff) | 0 |
| Tie (in-state) | 5 | 5 + 2 × (div_diff) | 5 |
| Tie (out-of-state, opp has a tie) | 5 + 0.5 | + play-up | + play-up |
| Double Forfeit | +1 to the team that defeated BOTH forfeiting teams | — | — |

**Play-up points (post-April-2023 amendment):**

- Pre-April-2023: based on enrollment **classification** (5A/4A/3A/2A/1A).
- Post-April-2023: based on **playoff division** (I/II/III/IV/V — depending on sport-year).
- For Football 2022 onward, the playoff division basis is the only one in effect (Football Div I-IV since 2022 restructure).

## Inclusion criteria

### Counted toward power rating:
- **Regular-season games only** (Section 14.12.2)
- Both in-state and out-of-state opponents (Section 14.12.3)

### NOT counted toward power rating:
- **Jamborees** — separately sanctioned per Section 6.5; treated as a distinct event class, not regular-season games. Fee $200 varsity / $100 sub-varsity. Approved via Football Jamboree sanctioning form.
- **Scrimmages** — interscholastic scrimmages are sanctioned but not counted as regular-season games.
- **Playoff games** — bi-district through finals; tracked separately on playoff brackets.
- **JV / B-team / sub-varsity games** — implied throughout (the power-rating system is varsity-only); explicit in Section 14 of the LHSAA Handbook.
- **Games added to schedule AFTER the 8th playing date** — per 2023 deadline of Oct 21, no schedule additions are eligible for power-rating inclusion after that.

## Out-of-state opponents (Section 14.12.3 + 6.12.2)

- LHSAA's **U1 Update Out of State Schools' Records Tool** is the canonical mechanism: home team must enter the opponent's running W/L weekly.
- Out-of-state classification is determined by enrollment via the opponent's state association, mapped to LHSAA's enrollment bands.
- **Cutoff rule:** if the out-of-state opponent has games remaining after LHSAA's 10th playing date, that specific game is NOT used in the power-rating computation.
- **Capped tally rule:** if an out-of-state opponent plays >10 regular-season games by LHSAA's 10th playing date, only its first 10 games count toward the opponent-strength component.

## Forfeit handling (14.12.1)

- **Single forfeit:** treated as the on-paper result (W for the non-forfeiting team, L for the forfeiting team).
- **Double forfeit:** +1 bonus point is awarded to whichever team had previously defeated both teams that subsequently forfeited.

## Cancellation handling

- Not explicitly enumerated in the 2023 Football Bulletin. Practical implication: a game cancelled by mutual agreement that is NOT replaced does not appear in `power_rating.online`'s tally (no result reported = no contribution).
- For cross-source modeling purposes, treat as "absent game" rather than 0-0 tie.

## Reporting / dispute window (Section 6.12.2)

- Home team principal/designee enters score by **midnight** the day of contest.
- Opponent coach receives a confirmation email; must confirm by **4:00 PM the next day** or the reported score stands.
- Weekly disputes due by **10:00 PM Monday** following each playing date.
- For Football Week 10: disputes due by **10:00 PM Saturday** that same week.
- After the deadline, results are **frozen** and used for the published Power Rating.
- **$50 fine** per missed weekly report.

## Implications for our cross-source check (`audit/cross_source.py`)

When comparing our `games` table W/L to LHSAA's published Power Rating PDF W/L:

1. **Subset filter — exclude before counting our games:**
   - Drop games where `is_playoff = true` or `is_championship = true`.
   - Drop games where `game_type = 'jamboree'` (when this column exists; pre-2026-05-25 the games table doesn't carry a jamboree flag — open question).
   - Drop scrimmages (similarly, may need a column to encode).
   - Drop games added after each sport's "8th playing date" deadline (sport-specific; football = Oct 21 for the 2023 season).

2. **Snapshot interpretation:**
   - "Week 10 Final" PDFs reflect state at end of regular season — apply `week_number <= 10` filter for football.
   - For non-football sports, "Final" snapshots reflect state immediately before playoffs — week-based filtering varies by sport.

3. **Out-of-state caveat:**
   - LHSAA's published count for any team includes their out-of-state games (per U1 Update Tool).
   - Our `games` table currently filters `is_out_of_state = false` in the audit's `_is_final_with_scores` helper, which DROPS those games on our side. This is an asymmetry that inflates Cat 1 lower bounds (we appear to have FEWER games than LHSAA). Worth re-examining.

4. **Forfeit rows:**
   - Our games table has `status = 'forfeit'`. These produce a normal W/L for the non-forfeiting side. Already handled correctly by `_wl_as_of`.

5. **Tied games:**
   - Ties are 5-point contests in the formula but are excluded from the W/L COUNTS the PDF publishes (W and L columns are separate from the formula's tie contribution). Our W/L diff comparison correctly excludes ties on both sides.

## Provenance notes

- Section numbers in this document map to the 2023-24 LHSAA Handbook (Section 14 = Football, Section 6 = General). Other sports have parallel sections in their respective bulletins:
  - Section 7 = Baseball, 8 = Basketball, 9 = Soccer, 10 = Softball, 11 = Volleyball (numbering varies by year — verify per bulletin).
- The April-2023 play-up change (class-based → division-based) is documented in the [2023 Annual Convention voting results](https://www.lhsaa.org/siteuploads/editorimg/file/Annual%20Convention/2023%20Final%20Voting%20Results%20Article%204_4_4%20Proposals.pdf).
- Annual revisions: re-check this document each off-season against the new bulletin. LHSAA has amended the power-rating formula multiple times (2022, 2023, 2024).

## Source URLs

- 2023 Football General Info Bulletin: `https://www.lhsaa.org/siteuploads/editorimg/file/Football/2023%20Football%20General%20Info%20Bulletin.pdf`
- 2024 Football Playoff Bulletin: `https://www.lhsaa.org/siteuploads/lhsaa/1642_pdf_2024-football-playoff-bulletin.pdf`
- 2025 Annual Convention voting (Wild Card Section 10.10): `https://www.lhsaa.org/siteuploads/editorimg/file/Annual%20Convention/2025%20LHSAA%20Final%20Voting%20Results%202-4-2025.pdf`
