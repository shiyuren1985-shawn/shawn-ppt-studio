# Shawn PPT Studio

Shawn PPT Studio is a local, conversation-first workspace for building visual PowerPoint decks with Codex. It keeps the outline, selected slide images, candidate review, image retouching, and export workflow in one macOS app.

> **Developer preview:** the source and the `shawn-ppt-image` project Skill are public. The full image-production workflow still depends on a compatible, signed-in Codex environment and its system `imagegen` Skill.

## What is included

- A three-column outline workspace with resizable and collapsible panels.
- A project-level Codex conversation with streamed items, steering, interrupt, history, and official approval prompts.
- Editable long-term Studio rules that persist locally across every project and conversation; explicit `记住，…` and `…。记住这个要求` messages can add a rule directly.
- A native candidate-selection workspace with three images per row, immediate selection, zoom, and Trash support.
- New-project flows for an empty folder or an existing Markdown outline.
- Canonical Fast8 and single-image-edit adapters. A bundled Skill at `.agents/skills/shawn-ppt-image` remains available as a distribution fallback.
- PDF and ordered page-image ZIP export. PPTX export remains unavailable until a real Microsoft Office sensitivity label can be verified.
- A Tauri desktop shell for macOS.

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

### Optional legacy integration

Legacy EPC/SI projects can connect to a sibling `saturated-ppt` selector service. New Studio projects keep their own local candidate and selection state and do not require legacy project data.

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
| `CODEX_HOME` | Codex data and skill directory; defaults to `~/.codex` |
| `CODEX_BIN` | Explicit Codex executable |
| `SHAWN_PPT_STUDIO_NODE` | Node.js executable used by the desktop shell |
| `SHAWN_PPT_STUDIO_PYTHON` | Python executable used by the production adapter |
| `SHAWN_PPT_STUDIO_RUNTIME_ROOT` | Runtime containing export tools |
| `SHAWN_PPT_STUDIO_SELECTOR_ROOT` | Optional legacy selector checkout |
| `SHAWN_PPT_STUDIO_DECKS_FILE` | Optional legacy deck registry |
| `SHAWN_PPT_IMAGE_SKILL_ROOT` | Optional standalone `shawn-ppt-image` checkout; overrides both the installed and bundled copies |
| `SHAWN_PPT_IMAGE_MONITORING_ROOT` | Shared image-generation slot registry |

## Updating the distribution fallback

The installed Skill is the local live source. The bundled copy is retained only for distributing Studio to machines without that Skill. Before publishing a new Studio build, update that fallback from the standalone repository:

```bash
./bin/sync-shawn-ppt-image
```

The script validates a clean standalone checkout, pushes its `main` branch, runs the Skill tests, and updates the Studio subtree. Review and test the resulting Studio commit before publishing Studio.

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

## Platform status

- **Apple Silicon macOS:** the only currently tested desktop target. The local `.app` is ad-hoc signed and not notarized.
- **Intel macOS:** not tested and no universal binary is currently published.
- **Windows/Linux:** Codex itself supports these platforms, but this Studio does not yet ship a Windows or Linux desktop build. Porting requires replacing the macOS picker/Finder integration and validating desktop packaging and export tools.

## Data and safety boundaries

- Projects, conversations, selections, and generated artifacts remain local unless the user explicitly publishes them.
- The repository does not contain company documents or generated slide images.
- Codex approvals and sandbox decisions come from the official App Server protocol; the UI does not invent a second approval system.
- Candidate identity and file validation are retained only where needed to prevent selecting or overwriting the wrong slide.

## License

No open-source license has been selected yet. The repository is public for review and collaboration; redistribution and reuse terms should be chosen before broader distribution.
