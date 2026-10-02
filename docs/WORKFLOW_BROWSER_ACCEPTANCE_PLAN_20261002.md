# Browser acceptance before activating the new workflows

Use the existing browser runner with its own temporary SQLite database, synthetic
demo account, private test encryption keys and free loopback port. Main, Preview,
existing uploads and real integration credentials are outside this test.

1. Create different object-specific templates through the actual form, publish
   them through the real HTTP backend and verify the returned immutable steps.
2. Select object, unit, contract, published template and handover date in the UI.
   Start one change after a real server preview. Lose only its committed HTTP
   response and repeat the original command from the UI: identical command and
   saved response, exactly one change, original due date unchanged.
3. Link a real ordinary task, complete its workflow step and complete the change.
   Reload the browser and verify persisted state, task projection and original
   dates. Publish an amended template version and prove the started change still
   retains its original version and step text.
4. Start the other object's workflow and verify its different deadline and step
   text. No task or template from the first object may be substituted.
5. Check the actual page at 320, 360 and desktop widths, retaining screenshots of
   synthetic data. Any overflow is a finding to repair before promotion, not a
   reason to weaken the assertion. Review the subsequent UI polish with the same
   real browser cases.

Addendum before the compact-preparation test change: verify Unknown keeps the
existing preparation open, actual committed success collapses it, reopening
retains the exact property/unit context and the same form instance, and a second
success is compact at all three widths. Reopen explicitly when the next test
action needs the existing preparation. Viewport images prove real sidebar
geometry independently of Chromium full-page sticky-element capture artifacts.

API requests prepare ordinary property/tenant/contract fixtures and inspect
persisted facts. Template publication, start, exact retry, task link and completion
remain real user actions. The test may intercept a response after real server
execution solely to reproduce a lost reply; it never substitutes business data.
