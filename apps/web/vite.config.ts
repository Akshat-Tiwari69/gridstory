import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The GitHub Pages demo lives under /<repo>/. GRIDSTORY_BASE is the bare repo name: a value
// starting with "/" gets rewritten into a Windows path by Git Bash.
// Accepts "gridstory" or "/gridstory/"; slashes are normalised so the result is "/gridstory/".
const segment = (process.env.GRIDSTORY_BASE ?? '').replace(/^\/+|\/+$/g, '')
const base = segment ? `/${segment}/` : '/'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  base,
})
