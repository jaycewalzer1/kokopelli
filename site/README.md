# kokopelli-labs.com

The public site: one static page in the pre-seed deck's look (DESIGN.md tokens, the deck's textures and glyphs from
`docs/brand/deck/`). No build step. `.github/workflows/site.yml` publishes this folder to GitHub Pages on every push to
main that touches it.

Preview: `python3 -m http.server -d site 8798`. The benchmark numbers are copied by hand from
`experiments/bystander/README.md`; update them here when a new run replaces them.
