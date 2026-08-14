# LogHub 2.0 archives

This directory contains the complete local LogHub 2.0 dataset download as the
14 original ZIP archives. Each archive contains the raw log, structured CSV,
and template CSV for one dataset. The archives are stored with Git LFS, so run
`git lfs pull` after cloning if they were not downloaded automatically.

Extract them into the location expected by the evaluation scripts:

```sh
mkdir -p data/loghub-2.0/extracted
for archive in data/loghub-2.0/archives/*.zip; do
  unzip -q "$archive" -d data/loghub-2.0/extracted
done
```

The data is licensed for research or academic work. See `LICENSE`; use or
distribution must refer to https://github.com/logpai/loghub-2.0 and cite the
LogHub papers listed there.
