# __COURSE_TITLE__

Slides (Quarto, reveal.js) and example code. Built with the shared tools in `_extensions/se-slides`
(Git submodule, repository `se-buw/se-slides`). How to write slides: `_extensions/se-slides/README.md`.

## Setup

```powershell
git clone --recurse-submodules https://github.com/se-buw/__REPO__.git
./_extensions/se-slides/tools/bootstrap.ps1     # once per computer: Quarto and JDK 25
```

## Build

```powershell
./build.ps1 05 -Preview      # live preview of lecture 05
./build.ps1 05 -Pdf          # HTML and PDF of lecture 05 (_site/)
./build.ps1 -Pdf -Moodle     # everything, plus dist/moodle-<date>.zip
```

## Contents

```
lectures/NN-topic.qmd    slides
code/NN-topic/           example code of that lecture (compiled and run by the build)
images/ + credits.yml    images with source and licence
_variables.yml           course title, semester data, quiz link
```

## Update the shared tools

```powershell
git submodule update --remote _extensions/se-slides
./build.ps1 -Pdf -Strict
git commit -am "Update se-slides"
```
