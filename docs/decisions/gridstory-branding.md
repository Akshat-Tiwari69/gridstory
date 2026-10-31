# GridStory branding

- **Decision:** The board selected the name GridStory. The GitHub Pages base path is `/gridstory/`.
- **Local workspace:** the checkout path stays `/mnt/f/Code/Projects/PitWall`; it is not renamed.
- **Reason:** consistent branding across the app, assets, docs and the published demo.
- **Build config:** `GRIDSTORY_BASE` sets the Vite base. `gridstory` and `/gridstory/` both yield `/gridstory/`; unset yields `/`.
- **Publication tooling:** when WSL uses the Windows Python environment, publish with Windows Node and translate the export destination with `wslpath`. This reuses the installed dependencies and keeps demo data in the actual web build directory.
