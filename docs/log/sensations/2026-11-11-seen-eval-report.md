# seen(): which detector confirms a sim person in a painted frame

A copy, kept in git, of `out/sensation/seen_eval/20261110/report.md` as queue job `sens_seen_eval` wrote it on 2026-11-11 at 00:10 (commit 916412d, clean tree). The audit sheets, `run.json`, `report.json`, `chosen_backend.json` and every detection are in that folder; what the numbers mean is in `2026-11-11-seen.md`.

Frames: `out/bodies/demo/runs/wm` (Cosmos3-Nano-Sim-Transfer, 8-bit, 448x256, 16 fps), both agents' painted films. Headline part (up to 52 s, every 0.5 s): 210 frames, of which the sim's segmentation shows a person in 72, nobody in 50, and 88 are left out as unclear. After the mosaic sets in (every 1 s): 136 frames, person in 136, nobody in 0, unclear 0.

Shortened to save model time: the detectors were shown only the frames that are scored, 122 headline frames and every 4th frame after the mosaic (34), and each backend had 180 s of detecting.

On each frame seen() gets one candidate, "a person", with no box. Precision: of the frames where it was confirmed, the share where the sim's segmentation has a person on screen. Recall: of the frames where it has one, the share confirmed. The bar is the best recall at precision >= 0.9 with a median under 1 s per frame.

| Backend | Threshold | Precision | Recall | TP / FP / FN / TN | Median s | p95 s | Load s | Passes |
|---|---|---|---|---|---|---|---|---|
| owlv2 | none reaches 0.9 (best precision 0.74 at 0.3, recall 0.5139) | | | 37 / 13 / 35 / 37 | 0.248 | 0.277 | 3.74 | no |
| grounding_dino | 0.8 | 1.000 | 0.292 | 21 / 0 / 51 / 50 | 0.342 | 0.397 | 2.76 | yes |
| florence2 | none reaches 0.9 (best precision 0.8448 at 0.05, recall 0.6806) | | | 49 / 9 / 23 / 41 | 0.194 | 0.341 | 2.64 | no |
| florence2_ground | none reaches 0.9 (best precision 0.5902 at 0.05, recall 1.0) | | | 72 / 50 / 0 / 0 | 0.125 | 0.159 | 2.41 | no |

**Pick: grounding_dino.**

## At each backend's own threshold from the table

| Backend | Small people (under 60 px tall): recall | Larger: recall | With the sim's box (IoU >= 0.3): recall | After the mosaic: precision, recall |
|---|---|---|---|---|
| grounding_dino | 0.000 (0 of 23) | 0.429 (21 of 49) | 0.292 (21 of 72) | 1.000 (12 of 12), 0.353 (12 of 34) |

## Every threshold, headline part

**owlv2**

| Threshold | Precision | Recall | TP | FP | FN | TN |
|---|---|---|---|---|---|---|
| 0.05 | 0.6514 | 0.9861 | 71 | 38 | 1 | 12 |
| 0.1 | 0.6667 | 0.9167 | 66 | 33 | 6 | 17 |
| 0.15 | 0.6703 | 0.8472 | 61 | 30 | 11 | 20 |
| 0.2 | 0.6667 | 0.8056 | 58 | 29 | 14 | 21 |
| 0.25 | 0.6933 | 0.7222 | 52 | 23 | 20 | 27 |
| 0.3 | 0.74 | 0.5139 | 37 | 13 | 35 | 37 |
| 0.35 | 0.375 | 0.0833 | 6 | 10 | 66 | 40 |
| 0.4 | 0.0 | 0.0 | 0 | 1 | 72 | 49 |
| 0.45 | None | 0.0 | 0 | 0 | 72 | 50 |
| 0.5 | None | 0.0 | 0 | 0 | 72 | 50 |
| 0.55 | None | 0.0 | 0 | 0 | 72 | 50 |
| 0.6 | None | 0.0 | 0 | 0 | 72 | 50 |
| 0.65 | None | 0.0 | 0 | 0 | 72 | 50 |
| 0.7 | None | 0.0 | 0 | 0 | 72 | 50 |
| 0.75 | None | 0.0 | 0 | 0 | 72 | 50 |
| 0.8 | None | 0.0 | 0 | 0 | 72 | 50 |
| 0.85 | None | 0.0 | 0 | 0 | 72 | 50 |
| 0.9 | None | 0.0 | 0 | 0 | 72 | 50 |
| 0.95 | None | 0.0 | 0 | 0 | 72 | 50 |

**grounding_dino**

| Threshold | Precision | Recall | TP | FP | FN | TN |
|---|---|---|---|---|---|---|
| 0.05 | 0.5902 | 1.0 | 72 | 50 | 0 | 0 |
| 0.1 | 0.5902 | 1.0 | 72 | 50 | 0 | 0 |
| 0.15 | 0.5902 | 1.0 | 72 | 50 | 0 | 0 |
| 0.2 | 0.6 | 1.0 | 72 | 48 | 0 | 2 |
| 0.25 | 0.6036 | 0.9306 | 67 | 44 | 5 | 6 |
| 0.3 | 0.6774 | 0.875 | 63 | 30 | 9 | 20 |
| 0.35 | 0.7375 | 0.8194 | 59 | 21 | 13 | 29 |
| 0.4 | 0.7639 | 0.7639 | 55 | 17 | 17 | 33 |
| 0.45 | 0.7778 | 0.6806 | 49 | 14 | 23 | 36 |
| 0.5 | 0.7705 | 0.6528 | 47 | 14 | 25 | 36 |
| 0.55 | 0.7586 | 0.6111 | 44 | 14 | 28 | 36 |
| 0.6 | 0.8 | 0.6111 | 44 | 11 | 28 | 39 |
| 0.65 | 0.7885 | 0.5694 | 41 | 11 | 31 | 39 |
| 0.7 | 0.8125 | 0.5417 | 39 | 9 | 33 | 41 |
| 0.75 | 0.8919 | 0.4583 | 33 | 4 | 39 | 46 |
| 0.8 | 1.0 | 0.2917 | 21 | 0 | 51 | 50 |
| 0.85 | 1.0 | 0.0417 | 3 | 0 | 69 | 50 |
| 0.9 | None | 0.0 | 0 | 0 | 72 | 50 |
| 0.95 | None | 0.0 | 0 | 0 | 72 | 50 |

**florence2**

| Threshold | Precision | Recall | TP | FP | FN | TN |
|---|---|---|---|---|---|---|
| 0.05 | 0.8448 | 0.6806 | 49 | 9 | 23 | 41 |
| 0.1 | 0.8448 | 0.6806 | 49 | 9 | 23 | 41 |
| 0.15 | 0.8448 | 0.6806 | 49 | 9 | 23 | 41 |
| 0.2 | 0.8448 | 0.6806 | 49 | 9 | 23 | 41 |
| 0.25 | 0.8448 | 0.6806 | 49 | 9 | 23 | 41 |
| 0.3 | 0.8448 | 0.6806 | 49 | 9 | 23 | 41 |
| 0.35 | 0.8448 | 0.6806 | 49 | 9 | 23 | 41 |
| 0.4 | 0.8448 | 0.6806 | 49 | 9 | 23 | 41 |
| 0.45 | 0.8448 | 0.6806 | 49 | 9 | 23 | 41 |
| 0.5 | 0.8448 | 0.6806 | 49 | 9 | 23 | 41 |
| 0.55 | 0.8448 | 0.6806 | 49 | 9 | 23 | 41 |
| 0.6 | 0.8448 | 0.6806 | 49 | 9 | 23 | 41 |
| 0.65 | 0.8448 | 0.6806 | 49 | 9 | 23 | 41 |
| 0.7 | 0.8448 | 0.6806 | 49 | 9 | 23 | 41 |
| 0.75 | 0.8448 | 0.6806 | 49 | 9 | 23 | 41 |
| 0.8 | 0.8448 | 0.6806 | 49 | 9 | 23 | 41 |
| 0.85 | 0.8448 | 0.6806 | 49 | 9 | 23 | 41 |
| 0.9 | 0.8448 | 0.6806 | 49 | 9 | 23 | 41 |
| 0.95 | 0.8448 | 0.6806 | 49 | 9 | 23 | 41 |

**florence2_ground**

| Threshold | Precision | Recall | TP | FP | FN | TN |
|---|---|---|---|---|---|---|
| 0.05 | 0.5902 | 1.0 | 72 | 50 | 0 | 0 |
| 0.1 | 0.5902 | 1.0 | 72 | 50 | 0 | 0 |
| 0.15 | 0.5902 | 1.0 | 72 | 50 | 0 | 0 |
| 0.2 | 0.5902 | 1.0 | 72 | 50 | 0 | 0 |
| 0.25 | 0.5902 | 1.0 | 72 | 50 | 0 | 0 |
| 0.3 | 0.5902 | 1.0 | 72 | 50 | 0 | 0 |
| 0.35 | 0.5902 | 1.0 | 72 | 50 | 0 | 0 |
| 0.4 | 0.5902 | 1.0 | 72 | 50 | 0 | 0 |
| 0.45 | 0.5902 | 1.0 | 72 | 50 | 0 | 0 |
| 0.5 | 0.5902 | 1.0 | 72 | 50 | 0 | 0 |
| 0.55 | 0.5902 | 1.0 | 72 | 50 | 0 | 0 |
| 0.6 | 0.5902 | 1.0 | 72 | 50 | 0 | 0 |
| 0.65 | 0.5902 | 1.0 | 72 | 50 | 0 | 0 |
| 0.7 | 0.5902 | 1.0 | 72 | 50 | 0 | 0 |
| 0.75 | 0.5902 | 1.0 | 72 | 50 | 0 | 0 |
| 0.8 | 0.5902 | 1.0 | 72 | 50 | 0 | 0 |
| 0.85 | 0.5902 | 1.0 | 72 | 50 | 0 | 0 |
| 0.9 | 0.5902 | 1.0 | 72 | 50 | 0 | 0 |
| 0.95 | 0.5902 | 1.0 | 72 | 50 | 0 | 0 |

## Models

| Backend | Model | Weights (repo@revision) | Licence | Device | Peak memory (process, Metal) GB |
|---|---|---|---|---|---|
| owlv2 | OWLv2 base (patch 16, ensemble) | `google/owlv2-base-patch16-ensemble@cfd3195ba4ea9592eec887ded089f4c08eff231d` | Apache-2.0 | mps | 0.62, 1.14 |
| grounding_dino | Grounding DINO tiny | `IDEA-Research/grounding-dino-tiny@a2bb814dd30d776dcf7e30523b00659f4f141c71` | Apache-2.0 | mps | 0.71, 3.49 |
| florence2 | Florence-2-base, <OD> task | `florence-community/Florence-2-base@00921df66db728a9ceb750f5eca43e5c203a2051` | MIT | mps | 0.79, 1.35 |
| florence2_ground | Florence-2-base, <CAPTION_TO_PHRASE_GROUNDING> task | `florence-community/Florence-2-base@00921df66db728a9ceb750f5eca43e5c203a2051` | MIT | mps | 0.71, 1.34 |

## What this does not show

- One run, two views, frames half a second apart: neighbouring frames are nearly the same picture, so the counts overstate how much was seen.
- One kind of thing. Nothing here says how a backend does on a ball, a bench or an egg.
- The truth is the sim's segmentation read back from an H.264 control video, with the human colours matched by hand. The audit sheets beside this report show every frame with its label.
- A false positive is a frame where the detector found a person and the sim has none on screen. Cosmos paints passers-by of its own (its prompt mentions neighbours), so some of these are the detector being right about the picture; for the leak they are still wrong.
- Florence-2 gives no confidence, so its row is one operating point, not a threshold choice.
- Latency is one 448x256 frame, one label, on this Mac, warm; the first frame and the load are listed apart.
