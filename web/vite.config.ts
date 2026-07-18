import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
    plugins: [react()],
    server: {
        host: '0.0.0.0', // Listen on all network interfaces
        port: 3600,
        watch: {
            usePolling: true,
        }
    },
    preview: { port: 4173 },
    resolve: {
        alias: {
            '@': path.resolve(__dirname, './src')
        }
    }
})
