# Shared web demo assets

Includes Centerfield floor 18 and floor 1 compressed display GLBs, collision meshes,
sampled evidence images, saved hazard analysis, review state, and analysis history.
GLBs use Git LFS. Original videos, original uncompressed GLBs, raw depth sessions,
credentials, and temporary outputs are excluded.

From the repository root:

```sh
git lfs install
git lfs pull
cd zipbul
npm ci
npm run demo:setup
npm run dev
```

`demo:setup` installs portable assets into the gitignored `data/scenes` directory.
It preserves any scene that already exists. `ZIPBUL_DATA_DIR` can select another
runtime scene directory. Setup does not call AI APIs.

The package supports 3D viewing, walkthrough collision, saved hazard/graph views,
and sampled evidence images. Full video playback and new full-video analysis
require the separately supplied original video; original-mesh download likewise
requires the original GLB. This package is not a standalone static GitHub Pages build:
the existing Next.js application and Node API must run.
