import type { Config } from 'tailwindcss'

export default {
    content: ['./index.html', './src/**/*.{ts,tsx}'],
    theme: {
        extend: {
            fontFamily: {
                sans: ['"Buenos Aires"', '"OpenSans"', '"Open Sans"', 'sans-serif']
            },
            colors: {
                brand: { DEFAULT: '#2563eb', dark: '#1e40af' }
            }
        }
    },
    plugins: []
} satisfies Config
