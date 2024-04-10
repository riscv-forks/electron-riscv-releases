# Electron RISC-V Releases

This repository contains maintaince scripts and CI configs for electron RISC-V releases.

Due to the limitations of GitHub Actions, I cannot place the CI in the fork repo because
it will collide with upstream CI configs.

Close to upstream releases are published in GitHub releases.

The source repo of electron RISC-V fork is https://github.com/riscv-forks/electron

The build instructions are also in the fork repo.

# TODO

- For now the CI uses a persistent systemd-nspawn container. 
Ideally it should be ephemeral and well documented in a Dockerfile.
- The CI yaml and procedure need to be improved.
