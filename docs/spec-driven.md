# Spec-Driven Development with Codex

This project uses the official [GitHub Spec Kit 1.4.1](https://github.com/github/spec-kit/releases/tag/v1.4.1),
the latest stable release verified on November 17, 2026.
Spec Kit describes upcoming application changes; the existing template provides
the infrastructure and quality checks. Author all Spec Kit artifacts in English.

## Included configuration

- `.agents/skills/speckit-*/SKILL.md`: nine official Codex skills.
- `.specify/`: templates, Bash scripts, integration state, and workflows from release 1.4.1.
- `.specify/memory/constitution.md`: four core principles, version 2.0.0.
- `AGENTS.md`: references to the constitution and existing template documentation.

Dependency versions, the stack, quality thresholds, and deployment settings remain
in the README, Makefiles, and application configuration. They are not duplicated
in the constitution. Official templates remain unmodified to support upgrades.

## Local CLI

The skills are already in the repository. On a new machine, install the pinned CLI
and verify the configuration from the repository root:

```bash
make spec-install
make spec-check
```

The CLI is a separate `uv tool`, outside backend dependencies and the Vercel
deployment. Codex discovers project skills in `.agents/skills`; setting
`CODEX_HOME` is unnecessary. If new skills do not appear in the picker, restart Codex.
[Codex skills documentation](https://learn.chatgpt.com/docs/build-skills).

## Developing a feature

Enter these commands one at a time **in Codex chat**, using the `$` prefix:

```text
$speckit-specify Describe the feature, its user, and the expected outcome.
$speckit-clarify
$speckit-plan Use the existing api/ and web/ template and its configuration.
$speckit-tasks
$speckit-analyze
$speckit-implement
$speckit-converge
```

`clarify` resolves ambiguities, `analyze` checks consistency before implementation,
and `converge` identifies remaining gaps. If tasks remain, continue with `implement`
and `converge`. Use `$speckit-checklist` to assess requirements quality.
`$speckit-constitution` updates project principles; the initial constitution is
already complete and does not need to be recreated.

Feature artifacts go in `specs/NNN-name/`. The current-feature pointer,
`.specify/feature.json`, is local and ignored by Git. This project does not have
the Git management extension installed; manage branches and commits with the
repository's usual tools. You do not need to reconstruct a specification for the
entire existing template before starting the first feature.

After implementation, run the existing checks and pre-commit commands described
in the [README](../README.md#sprawdzenia-lokalne-i-pre-commit). Example infrastructure
tasks in the templates do not require rebuilding infrastructure that already exists.

## Installation and upgrades

The repository was initialized with the official command:

```bash
specify init --here --force --non-interactive \
  --integration codex --script sh \
  --integration-options="--events false"
```

Do not repeat `init` in an already configured checkout without reviewing local
changes. Check for a new release with `specify self check`. To upgrade, update
`SPEC_KIT_VERSION` in the Makefile, install the CLI, then run
`specify integration upgrade codex` and review the diff. Preserve the project's
constitution and `AGENTS.md`; run `make spec-check` after the upgrade.

Native Spec Kit event handlers are disabled. The skills work without additional
Codex hooks, and local pre-commit still runs the quality checks. No presets,
extensions, or GitHub Actions were installed. The configuration does not set the
Codex model or permissions.

Sources: [Codex integration](https://github.com/github/spec-kit/blob/v1.4.1/docs/integrations/codex.md),
[adoption in an existing project](https://github.com/github/spec-kit/blob/v1.4.1/docs/how-to/existing-projects.md),
[installation](https://github.com/github/spec-kit/blob/v1.4.1/docs/installation.md).
