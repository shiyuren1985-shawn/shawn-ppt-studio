# Shawn PPT Studio

Shawn PPT Studio is a local, conversation-first workspace for building visual PowerPoint decks with Codex. It keeps the outline, selected slide images, candidate review, image retouching, and export workflow in one macOS app.

> **Developer preview:** the source is public, but the full image-production workflow is not yet plug-and-play for third parties. It currently depends on Codex and a separate `Shawn-PPT-image` skill that is not included in this repository.

## What is included

- A three-column outline workspace with resizable and collapsible panels.
- A project-level Codex conversation with streamed items, steering, interrupt, history, and official approval prompts.
- A native candidate-selection workspace with three images per row, immediate selection, zoom, and Trash support.
- New-project flows for an empty folder or an existing Markdown outline.
- Canonical Fast8 and single-image-edit adapters for the external `Shawn-PPT-image` skill.
- PDF and ordered page-image ZIP export. PPTX export remains unavailable until a real Microsoft Office sensitivity label can be verified.
- A Tauri desktop shell for macOS.

Company decks, private assets, production selection state, generated images, runtime logs, and internal QA evidence are intentionally excluded.

## Requirements

### Required for chat

- macOS for the current desktop build.
- Node.js 24 or newer.
- A signed-in Codex runtime. The app first looks for the Codex binary bundled with ChatGPT for macOS, then for `codex` on `PATH`. See the official [Codex CLI setup](https://developers.openai.com/codex/cli) and [App Server documentation](https://developers.openai.com/codex/app-server).

### Required for image generation and retouching

- The separate `Shawn-PPT-image` skill at `$CODEX_HOME/skills/Shawn-PPT-image`.
- The Codex `imagegen` skill at `$CODEX_HOME/skills/.system/imagegen`.
- The local Python/runtime dependencies used by those skills.

The `Shawn-PPT-image` skill is not public yet, so cloning this repository alone currently provides the UI, project management, Codex conversation, selection, and export code—but not the complete image-production pipeline.

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

The local build is ad-hoc signed for development. It is not Developer ID signed or notarized.

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
| `SHAWN_PPT_IMAGE_MONITORING_ROOT` | Shared image-generation slot registry |

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

- **macOS:** supported by the current desktop shell and native folder/file picker.
- **Windows/Linux:** Codex itself supports these platforms, but this Studio does not yet ship a Windows or Linux desktop build. Porting requires replacing the macOS picker/Finder integration and validating desktop packaging and export tools.

## Data and safety boundaries

- Projects, conversations, selections, and generated artifacts remain local unless the user explicitly publishes them.
- The repository does not contain company documents or generated slide images.
- Codex approvals and sandbox decisions come from the official App Server protocol; the UI does not invent a second approval system.
- Candidate identity and file validation are retained only where needed to prevent selecting or overwriting the wrong slide.

## License

No open-source license has been selected yet. The repository is public for review and collaboration; redistribution and reuse terms should be chosen before broader distribution.
