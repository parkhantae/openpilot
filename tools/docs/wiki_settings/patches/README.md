# Settings Wiki patches

These patches preserve reviewed Wiki edits in the code branch when the author
cannot push to the separate Wiki repository. Committing a patch here does not
publish its content to the live Wiki.

## Porter one-shot deceleration recovery trial

`porter-decel-retry.patch` supplies Korean, English and Chinese MANUAL regions
for `PorterDecelRetry` and `CruiseButtonTest3`. Generate initial pages from the
current fork catalog, apply with `git apply --check --unidiff-zero` and
`git apply --unidiff-zero`, then regenerate and validate. The trial defaults OFF
and adds at most one deceleration-only press per stock-ON session after three
unanswered deceleration requests and a three-second quiet period. The unavailable
banner also applies with the trial OFF. It now includes the display-bound double
beep once per second, immediate cancellation and preserved alert priority/volume.
This fork-specific patch is staged,
not published to the upstream live Wiki.

## Cruise speed at accelerator release

`gas-release-speed.patch` supplies Korean, English and Chinese manual regions
for `AutoGasSyncSpeed` on `c3-pht-porter`. Generate fresh pages from this branch's
catalog, apply with `git apply --unidiff-zero`, regenerate with that staging
directory as `--wiki-dir`, and validate. It describes release-speed selection
instead of pedal-peak capture, interruption priority and the unchanged stock
button/PCM limitations. This patch does not publish to the upstream Wiki.

## Bosch passive reception

`bosch-passive-reception.patch` changes only the Korean and English
`EnableRadarTracks` manual regions. It documents the Bosch startup exception,
the unchanged activation-result parameter, and the distinction between passive
radar reception and vehicle control. It also corrects the stale mode-0 manual
description to match the current SCC-only policy.

The patch is based on `ajouatom/openpilot.wiki.git` commit
`d7117c2db74a5e683f9e8d4d2338ac68bebabff0` and corresponds to Wiki commit
`6fba8803dec100aeaecd9d4751bc205402699f78`. The Bosch behavior was verified on
the Bosch code branch; the text explicitly applies to versions supporting this
receiver. The candidate-platform wording (Elantra AD plus unvalidated i30 PD, Kona,
Kona Electric and K3 BD/Forte) was added on 2026-10-12, after that Wiki commit.

From a Wiki checkout, use the absolute path to this patch:

```sh
git apply --check --unidiff-zero /absolute/path/to/bosch-passive-reception.patch
git apply --unidiff-zero /absolute/path/to/bosch-passive-reception.patch
```

The patch uses zero context lines, so `--unidiff-zero` is required. Follow the
[authoring guide](../AUTHORING_GUIDE.md), validate the edited pages and regenerate
the Wiki catalog before publishing. If the check fails after later Wiki edits,
reconcile only the matching manual regions instead of forcing the patch.
## Tesla automatic turn signals

`tesla-auto-turn-signals.patch` fills only the Korean, English and Chinese
`TeslaAutoTurnSignals` manual regions. Its base is the initial pages generated
from the working catalog that introduces this setting. Generate those pages,
then check and apply the patch from the staged Wiki directory:

```sh
git apply --check /absolute/path/to/tesla-auto-turn-signals.patch
git apply /absolute/path/to/tesla-auto-turn-signals.patch
```

Regenerate with that directory as `--wiki-dir` to preserve the manual text,
then validate following the authoring guide. The review marker deliberately
remains unset; this patch and local verification do not publish or certify
vehicle behavior.


## RAV4 PCM mode 0

`rav4-pcm-mode0.patch` updates only the Korean and English `SpeedFromPCM`
manual regions from public Wiki commit `fbe96d08c066844a60dc909500c1e2d9393bca5d`.
It describes observed SET/RES speed synchronization for the exact 2022 RAV4
platform with PCM and direct longitudinal control, local-input priority, and
the preserved lower deceleration targets. It does not enable corner hardware
or add button transmission. The reviewed text was published to the live Wiki on
October 14 in commit `e4f2435`; the patch remains as the original review artifact.

```sh
git apply --check --unidiff-zero /absolute/path/to/rav4-pcm-mode0.patch
git apply --unidiff-zero /absolute/path/to/rav4-pcm-mode0.patch
```

The patch uses zero context lines. Validate both edited pages and regenerate the catalog using the authoring guide
before publishing. Reconcile later manual edits if the check fails.

## RAV4 radar display

`rav4-radar-display.patch` updates the Korean and English `ShowRadarInfo` manual
regions from Wiki commit `fbe96d08c066844a60dc909500c1e2d9393bca5d`. It describes
the separate ARS display stream on the standard device screen in mode 3,
unchanged control targets, freshness checks, and the web/mici limitation.
The reviewed text was published to the live Wiki on October 14 in commit `e4f2435`.

```sh
git apply --check --unidiff-zero /absolute/path/to/rav4-radar-display.patch
git apply --unidiff-zero /absolute/path/to/rav4-radar-display.patch
```

Only the matching manual regions are edited. Validate both pages and regenerate
the catalog before publishing, following the authoring guide.

## Porter configurable low-target cancellation

`porter-auto-cancel-below30.patch` supplies Korean/English/Chinese manual regions for
`PorterAutoCancelBelow30` and `PorterAutoCancelSpeed` on c3-pht-porter. The legacy
toggle key is retained; the adjacent speed setting controls the threshold, with
pending confirmation restarted on changes and the original automatic-SET speed
floor retained. Generate initial pages from that branch's current catalog, then
use `git apply --check --unidiff-zero` and `git apply --unidiff-zero` in the staged
Wiki directory; regenerate to preserve the reviewed manual content. Validate
before publishing. This branch-specific patch is not a live Wiki publication
and must not be generated from a catalog that lacks this setting.

## Porter common and dedicated GAP times

`porter-gap-times.patch` supplies branch-specific Korean/English manual regions
for common `TFollowGap1`–`TFollowGap4`, used when `PorterGapUse` is OFF.
`porter-dedicated-gap.patch` supplies the six dedicated setting explanations:
`PorterGapUse`, `PorterGap1`–`PorterGap4`, and `PorterLeadReactionTime`.
Dedicated mode shares its base settings between the Porter conventional-cruise
planner and button decisions, preserving both sets of stored values. Generate
from c3-pht-porter, apply both patches in staging and validate.
This patch is not published to the upstream live Wiki.

## Porter MAIN standby SET

`porter-main-set.patch` supplies reviewed Korean/English/Chinese manual regions for
`PorterAutoSetMain` on c3-pht-porter, including the automatic-SET sample deadline
and the 15 ms minimum between positive requests at the actual host dispatch clock.
Apply to staged pages generated from this branch with `git apply --check --unidiff-zero` and `git apply --unidiff-zero`, then
regenerate and validate.
The zero-context patch requires that flag. No live upstream Wiki publication.

`porter-press-spacing.patch` supplies Korean/English/Chinese manual regions for
`CruiseButtonTest1`. Generate fresh pages from this branch, apply with
`git apply --check --unidiff-zero` and `git apply --unidiff-zero`, regenerate and validate. It describes the
Porter-only pacing guard, skipped-sample consumption and unchanged driver/release
priority and pulse budgets. This is a staged patch, not a live Wiki publication.

## Porter comma 3 GAP touch selection

`porter-gap-touch.patch` updates the Korean/English `PorterGapUse` and
`CruiseGapLevels` manual regions for descending GAP selection from the comma 3
screen. Generate from the current c3-pht-porter catalog and apply this patch
with `git apply --unidiff-zero` **after** `porter-dedicated-gap.patch`; regenerate
and validate. The zero-context format requires the same flag for `--check`. This is a staged
branch-specific explanation, with no live upstream Wiki publication.

## Porter driver-torque release

`porter-steering-release.patch` documents the Porter-specific protective release
for `CustomSteerDeltaDown` and `CustomSteerDeltaDownLC` in Korean, English and
Chinese. Generate initial pages from the current c3-pht-porter catalog, apply
with `git apply --check` and `git apply`, then regenerate and validate. It changes
only those manual regions and is staged for this branch, not published upstream.

## Porter / Ioniq manual selection

The automatic-switch setting and its staged patch have been removed from both
fork catalogs. The comma Toggles action now writes the chosen vehicle and only
CAMERA SCC, radar tracks, HDA2 and steering-ratio values. This UI action has no
catalog parameter or generated setting page; its current behavior is documented in the Korean and
English user settings guides. Legacy automatic-switch Wiki pages must disappear
when regenerating from the matching branch catalog. No live upstream Wiki is changed.

## Porter and Ioniq 5 low-speed steering response

`low-speed-steering-response.patch` supplies reviewed Korean, English and Chinese
`LatSmoothSec` and `AutoTurnControl` explanations for the Porter II EV and Ioniq 5
HDA2 CAMERA SCC torque profiles. Generate fresh pages from this branch catalog,
apply with `git apply --check --unidiff-zero` / `git apply --unidiff-zero`,
regenerate and validate. It documents the low-speed duplicate-filter removal,
measured wheel-return completion and the bounded ten-second navigation request.
Torque, rate and driver-override limits remain. This branch-specific patch does
not publish to the live upstream Wiki.

## Porter adaptive following and confirmed SET speed

`porter-main-set.patch` includes one-shot comma-speed initialization from the
first confirmed OEM setting within 0.5 seconds of a qualified pedal-release cue.
It does not continuously mirror stock speed or grant engagement permission.

`porter-adaptive-gap.patch` updates Korean, English and Chinese MANUAL regions
for `PorterGapUse` and `PorterLeadReactionTime`. Generate from the branch catalog,
apply `porter-dedicated-gap.patch`, then `porter-gap-touch.patch`, then this patch
with `git apply --unidiff-zero`, and regenerate/validate. Dedicated GAP ON uses
own-speed distance plus lead speed/distance error and bounded target recovery;
OFF retains legacy following. This is staged branch documentation, not a live
publication to the upstream Wiki.

## Porter GAP state on stock-cruise restart

`porter-gap-restart.patch` adds Korean, English and Chinese `PorterGapUse`
MANUAL explanations for clearing the preceding session's GAP state after valid
stock OFF followed by ON. Current lead/navigation limits still apply; continuous
ON CAN gaps and invalid OFF samples retain protection. Generate fresh pages,
apply `porter-dedicated-gap.patch`, `porter-gap-touch.patch`,
`porter-adaptive-gap.patch`, then this patch with `git apply --unidiff-zero`.
Regenerate and validate. This staged fork-specific patch is not published to the
upstream live Wiki.

## Manual vehicle steering-ratio presets

`manual-vehicle-steering-ratio.patch` documents the comma Toggles action's
`CustomSR` presets for Porter II EV and Ioniq 5 HDA2, preserving the Porter
feature toggles and other manual tuning. Ignition-on Park choices are queued
for manager startup after an OS reboot; same-boot manager/card restarts keep
the active profile. Generate fresh pages from the matching
fork catalog, apply with `git apply --check --unidiff-zero` and
`git apply --unidiff-zero`, regenerate with staging as `--wiki-dir` and validate.
Only Korean, English and Chinese MANUAL regions change. This fork-specific
patch is staged; no live upstream Wiki publication.
