# Native branch selection and manual update lifecycle

The native Software page remained selectable when `SoftwareMenu=0`, but manager
did not run `updated`. The UI only sent signals to an absent process, so changing
the target could leave an old "up to date" date and no Download action. The
before-change UI/manager counterexamples fail on 59689dd96; both pass here.
The reporter's actual stored value was not captured, so this reproduces a
concrete failure path rather than proving every device-side cause.

Opening Software or explicitly checking/selecting/downloading now queues a
manual offroad request. Manager starts the updater for that request without
changing the background preference. The worker polls queued requests after its
handlers exist and during background sleeps, and exits after a manual task when
background updating is off. Policy-disabled and onroad actions remain blocked.
Onroad transition/manager initialization clear the request and busy state.

The page shows startup/check failures instead of reusing a stale success label.
Downloaded updates remain installable across a subsequent manual check only
when the freshly advertised origin branch and exact staged commit match.
Web-created local branch names use their configured remote branch as the
initial native target. All branch advertisements and downloads use origin.
Fetch is limited to the selected tip, without tag or recursive-submodule fetch;
the existing staging/submodule/AGNOS validation still runs afterward.

Native staging shares the live-repository transaction lock with Web Git work.
It waits for a bounded period rather than deleting locks. Child Git processes
inherit that lock and retain the existing process-group cleanup. Web background
ref refresh, pull and armed automatic reboot pause during native preparation or
while a native update awaits explicit Install. This prevents automatic fetches
from making live .git newer than .overlay_init and invalidating the staged swap.

Selection/check/download never write DoReboot. Only an offroad explicit Install
on a ready update requests reboot. This does not diagnose the earlier physical
boot loop; no live vehicle installation, overlay mount or OS flashing was done.

Validation uses actual GUI callbacks and updater transaction code with real
local Git remotes, including unrelated histories. Only widgets, vehicle/OS
interfaces and privileged overlay mounting are replaced. It covers cold start,
CHECK-to-DOWNLOAD-to-INSTALL, exact staging, recheck preservation, remote changes,
wrong origin/missing branch, staging/clock/startup errors, policy/onroad rejection,
lock waiting and Web arbitration. Native Params was rebuilt and its request and
onroad-clear behavior checked with an isolated store.

Additional startup regression checks reproduce two unchanged baseline failures:
test_params_check.py's native_result=1 harness omits launcher wrapper functions;
test_carrot_web_watchdog.py's restart wait test exceeds its five-second deadline.
The same case IDs fail on the untouched Porter base. These tests and their
launcher/restart code are outside this repair and are not claimed fixed.

KO/EN guides, localized setting summaries and UI messages are updated. The
SoftwareMenu Wiki manual patch is staged for this fork, without upstream Wiki
publication. c3-pht remains the exact carrot snapshot; this fix is for the
Porter and Ioniq vehicle branches only.
