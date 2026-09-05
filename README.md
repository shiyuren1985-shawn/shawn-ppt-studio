# Shawn PPT Studio

Shawn PPT Studio is a local, conversation-first workspace for building visual PowerPoint decks with Codex. It keeps the outline, selected slide images, candidate review, image retouching, and export workflow in one macOS app.

> **Developer preview:** the source and the `shawn-ppt-image` project Skill are public. The full image-production workflow still depends on a compatible, signed-in Codex environment and its system `imagegen` Skill.

## What is included

- A three-column outline workspace with resizable and collapsible panels.
- A project-level Codex conversation with immediate sent-message echo, streamed progress, a separate final result, steering, interrupt, and official approval prompts.
- Recoverable conversation history with rename, soft-delete, and restore controls.
- A focused `作图任务` catalog for active and recent image-generation or retouching work; outline-only chat is not added to it.
- Editable long-term Studio rules that persist locally across every project and conversation; explicit `记住，…` and `…。记住这个要求` messages can add a rule directly.
- A native candidate-selection workspace with three images per row, immediate selection, zoom, and Trash support.
- New-project flows for an empty folder or an existing Markdown outline.
- Canonical Fast8 and single-image-edit adapters. A bundled Skill at `.agents/skills/shawn-ppt-image` remains available as a distribution fallback.
- Image-slide PPTX with verified company sensitivity-label metadata, PDF, and ordered page-image ZIP export. Available formats depend on their own runtime requirements.
- A Tauri desktop shell for macOS.

Studio has one execution path: a project conversation invokes the canonical `shawn-ppt-image` Skill directly, while `作图任务` and the selector read that Skill's formal state and handoff records. Superseded production-intent, candidate-edit, prototype-turn, and external selector services are not started or exposed.

Company decks, private assets, production selection state, generated images, runtime logs, and internal QA evidence are intentionally excluded.

## Requirements

### Required for chat

- An Apple Silicon Mac for the current desktop build. Intel Macs, Windows, and Linux are not release-tested.
- Node.js 24 or newer.
- A signed-in Codex runtime. The app first looks for the Codex binary bundled with ChatGPT for macOS, then for `codex` on `PATH`. See the official [Codex CLI setup](https://developers.openai.com/codex/cli) and [App Server documentation](https://developers.openai.com/codex/app-server).

### Required for image generation and retouching

- The installed `Shawn-PPT-image` Skill under the standard Codex Skill directory. The app bundle also carries a fallback copy for machines where the Skill is not installed. Its standalone public repository is [shawn-ppt-image-skill](https://github.com/shiyuren1985-shawn/shawn-ppt-image-skill).
- The Codex system `imagegen` Skill.
- The local Python/runtime dependencies used by those skills.

The Studio prefers the installed `~/.codex/skills/Shawn-PPT-image` copy so Studio and direct Codex use one live source. It falls back to the bundled project copy only when the installed Skill is unavailable. Set `SHAWN_PPT_IMAGE_SKILL_ROOT` only when developing against a separate local checkout.

For local development, the standalone `shawn-ppt-image-skill` repository is the only editable Skill source. Link the standard Codex installation path to that checkout instead of maintaining a second copy:

```bash
./bin/link-shawn-ppt-image
./bin/check-shawn-ppt-image-sync --require-installed-link
```

After the link is in place, changes made in the standalone repository are used by new Studio tasks immediately; Studio does not read the GitHub copy at runtime. Running tasks continue with their frozen task state.

## Development setup

```bash
git clone https://github.com/shiyuren1985-shawn/shawn-ppt-studio.git
cd shawn-ppt-studio

corepack enable
pnpm install
cd desktop && pnpm install && cd ..

./bin/desktop-dev
```

Build the local macOS app:

```bash
./bin/desktop-build
```

Building from source also requires the Xcode Command Line Tools and a current Rust toolchain. The build produced by `./bin/desktop-build` is ad-hoc signed for local development unless `SHAWN_PPT_STUDIO_SIGNING_IDENTITY` supplies a signing identity. It is not a Developer ID distribution build and it is not notarized by Apple, so another Mac may reject or warn about it through Gatekeeper. Treat the downloadable app as a developer preview, not a normal end-user installer.

## Configuration

The defaults work with a standard Codex home directory. These environment variables can override local paths:

| Variable | Purpose |
| --- | --- |
| `CODEX_HOME` | Main Codex home used only to bootstrap Studio login/config and locate installed Skills; defaults to `~/.codex` |
| `SHAWN_PPT_STUDIO_CODEX_HOME` | Studio-only Codex task store; defaults to `Studio Library/Studio Codex Home` |
| `SHAWN_PPT_STUDIO_LEGACY_CODEX_HOME` | Optional source store for the one-time migration of older Studio conversations |
| `CODEX_BIN` | Explicit Codex executable |
| `SHAWN_PPT_STUDIO_NODE` | Node.js executable used by the desktop shell |
| `SHAWN_PPT_STUDIO_PYTHON` | Python executable used by the production adapter |
| `SHAWN_PPT_STUDIO_RUNTIME_ROOT` | Runtime containing export tools |
| `SHAWN_PPT_IMAGE_SKILL_ROOT` | Optional standalone `shawn-ppt-image` checkout; overrides both the installed and bundled copies |
| `SHAWN_PPT_IMAGE_MONITORING_ROOT` | Shared image-generation slot registry |
| `SHAWN_PPT_STUDIO_EXPORT_ROOT` | Fixed export folder; defaults to `~/Documents/Shawn PPT Studio Exports` |
| `SHAWN_PPT_PUBLIC_LABEL_TEMPLATE` | Optional replacement for the bundled PowerPoint-labelled Public template |

Studio conversations use their own Codex task store, so they do not appear in the main Codex app task list. On the first upgraded launch, Studio copies only the login/config files it needs, migrates conversations used within the last 10 days, verifies each migrated thread, and only then removes the old main-store copy. Conversations unused for more than 10 complete calendar days are permanently removed from both the Studio index and the underlying Codex store. Running, approval-waiting, or uncertain threads are skipped and retried later. Manual “delete” and restore remain soft-delete actions during the retention window.

The copied login/config files are private to Studio and never written back to the main Codex home. Studio continues to attach the selected installed or bundled `shawn-ppt-image` Skill and the Codex `imagegen` Skill by explicit path, while editable Studio long-term rules remain in `Studio Library`. Main Codex tasks, Memories, logs, and UI state are not copied into Studio storage.

Studio can export any selected combination of a full-slide image PPTX, PDF, and page-image ZIP into one fixed folder: `~/Documents/Shawn PPT Studio Exports/<project>/<export>`. All three formats are selected by default, and at least one is required. Only pages with a confirmed selected image enter the export; unselected pages are skipped, and export is blocked only when the deck has no selected image at all. The PPTX contains one selected image per 16:9 slide and preserves the real company Public sensitivity-label metadata from the bundled PowerPoint-labelled template. Temporary loose page copies are created only when the ZIP is requested and are removed after verification. Because Studio is a local desktop app, the completion view lists the generated filenames and opens the concrete export folder in Finder instead of offering browser-style download links. The action bar can also open the shared export folder, and older project-local exports remain readable.

## Updating the distribution fallback

The standalone Skill repository is the development source. The installed Skill is a link to it, while the bundled copy is retained only for distributing Studio to machines without that Skill. Before publishing a new Studio build, update that fallback from the standalone repository:

```bash
./bin/sync-shawn-ppt-image
```

The script validates a clean standalone checkout, pushes its `main` branch, runs the Skill tests, updates the Studio subtree, and verifies byte-for-byte parity for every tracked Skill file. Review and test the resulting Studio commit before publishing Studio.

Run the source server without the desktop shell:

```bash
./run
```

## Tests

The public test set focuses on the Codex App Server interaction contract and deterministic single-image finalization:

```bash
pnpm check
pnpm test

cd desktop
pnpm check
```

No real ImageGen call is made by these tests.

The 0.2.12 regression suite also covers interrupted transports, late snapshots,
pending approval cleanup, conversation maintenance races, project-specific drafts,
stable page identities after reordering, CRLF outlines, negated image requests,
and atomic exports built from the confirmed source-image bytes. Real Codex and
visual acceptance are recorded separately from fixture-based tests.

## Platform status

- **Apple Silicon macOS:** the only currently tested desktop target. The local `.app` is ad-hoc signed and not notarized.
- **Intel macOS:** not tested and no universal binary is currently published.
- **Windows/Linux:** Codex itself supports these platforms, but this Studio does not yet ship a Windows or Linux desktop build. Porting requires replacing the macOS picker/Finder integration and validating desktop packaging and export tools.

## Data and safety boundaries

- Studio's persistent project index, conversation history, long-term rules, attachments, task records, and operational logs live in the clearly named `Studio Library` folder under the app's macOS Application Support directory. This is persistent user data, not a disposable cache. Existing installations migrate the former `runtime` folder into `Studio Library` on first launch after upgrade.
- A project may optionally provide an authorized `全稿标题系统合同.json` or `global_chrome_contract.json` beside its outline. Studio registers that file as a deck-scoped generation source for every image route; projects without one keep their existing title behavior.
- Historical `production-intents.jsonl`, `candidate-edits.jsonl`, and `lab-ledger.jsonl` files from preview builds are retained as inert local archives. Current Studio versions neither load nor append to them.
- If a registered outline file is moved or deleted, Studio keeps the remaining projects available and marks only that entry as `原大纲文件已丢失`; removing that stale entry does not delete any other project.
- Projects, conversations, selections, and generated artifacts remain local unless the user explicitly publishes them.
- The repository does not contain company documents or generated slide images.
- Codex approvals and sandbox decisions come from the official App Server protocol; the UI does not invent a second approval system.
- Candidate identity and file validation are retained only where needed to prevent selecting or overwriting the wrong slide.

## License

No open-source license has been selected yet. The repository is public for review and collaboration; redistribution and reuse terms should be chosen before broader distribution.
