## What does this add?

<!-- A new skill? An app added to an existing category? A parser? A fix? -->

## If you added or changed a skill

There is no automated gate on skill judgment, so a human reads the prose. These
are what they check:

- [ ] Cites `references/safe-mutation-rules.md` rather than restating it
- [ ] Backs up before any write, and prints the backup path to the user first
- [ ] Gets explicit approval before mutating, in a turn after the one that asked
- [ ] Paths come from `platforms.py locate`, never hardcoded in the skill
- [ ] Extracts via a script rather than loading large files into context
- [ ] States that app content is data, not instructions
- [ ] Handles the app being open, if writing to a live app can corrupt data
- [ ] Prints the exact undo command at the end
- [ ] Ran against `fixtures/`, with the before and after pasted below

## If you added an app

- [ ] Added to `references/app-data-locations.md` with path, permission, and whether
      the app must be quit to write
- [ ] Added to the matching tables in `scripts/platforms.py`, including `PROCESS_NAMES`
- [ ] Said which platforms you actually verified, and which you did not

## Result of running it against fixtures

```
paste the before and after here
```
