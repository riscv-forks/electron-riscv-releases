# Electron RISC-V Releases

This repository contains maintaince scripts and CI configs for electron RISC-V releases.

Due to the limitations of GitHub Actions, I cannot place the CI in the fork repo because
it will collide with upstream CI configs.

Close to upstream releases are published in GitHub releases.

The source repo of electron RISC-V fork is https://github.com/riscv-forks/electron

The build instructions are also in the fork repo.

# Releases

We try to follow the upstream naming scheme for artifacts in the releases.
But for the debug/symbols zip files, it exceeds the 2GB limit of GitHub releases.
So they are uploaded in ztsd compressed tarball format.
And if the tarball is still too large, it will not be uploaded.

The releases are published in this repo instead of the fork repo because the fork repo
is already used to publish the toolchain that is used to build electron.

# Version Scheme

The version scheme is `<upstream version>.riscv<riscv revision>`.
But do note that this version scheme is only used by the tags in this repo.
For compatibility reasons, the released artifacts are using the upstream version scheme.

And to make the releases easier to use by various tools, releases are also uploaded to upstream tags.
Note that if a new riscv revision is made for an upstream version, that release will be re-uploaded.

# TODO

- For now the CI uses a persistent systemd-nspawn container. 
Ideally it should be ephemeral and well documented in a Dockerfile.
- The CI yaml and procedure need to be improved.
- The CI can't do parallel builds for now.
