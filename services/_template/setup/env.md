<!-- aihub-setup
id = "__ID__"
title = "__NAME__"
models = []
scan = []
summary = "__NAME__: one line on what it gives you"
gpu = false
disk_gb = 0.1
needs = []
check = "aihub check __ID__"

[[steps]]
run = "aihub install __ID__"
what = "makes .venv/ in this folder from requirements.txt (under 100 MB, a minute)"
-->

# __NAME__: setup

The format is in [docs/mods.md §9](../../../docs/mods.md#9-setup-docs). Rename this file after the environment (`<env>.md`), fill in the sections and the block above, and add one file per further environment. Delete a section only when it has nothing to say.

## What it is

What runs in this environment, and which features of the mod need it.

## Tested with

The versions on the machine this was written on, read from it: Python, the main packages, container image digests, upstream commits, binaries.

## Prerequisites

Other environments (link their docs), host packages ([host.md](../../../docs/setup/host.md)), accounts, licences.

## Install

```bash
aihub install __ID__
```

Makes `.venv/` in this folder from `requirements.txt`.

## Choosing models

What kind of model this mod runs, where the files go, and how to add your own. List one to three optional suggestions in the block above (`[[suggest]]`), with their sizes and licences; mark weights the mod can't run without as `required`.

## Configuration

| Key | Where | Required | Meaning |
|---|---|---|---|

## Check it works

```bash
aihub start __ID__ && aihub check __ID__
```

Expect `all checks passed`.

## What to look for

Known errors and their fixes; what's specific to `gfx1151`.

## Known gaps

Steps no script does yet.
