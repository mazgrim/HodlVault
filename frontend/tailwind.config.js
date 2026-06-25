/** @type {import('tailwindcss').Config} */

// Helper: a color shade driven by a CSS variable holding an "R G B" triplet,
// so Tailwind's opacity modifiers (e.g. bg-navy-800/60) keep working.
const v = (name) => `rgb(var(${name}) / <alpha-value>)`

export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        gold: {
          300: v('--c-gold-300'),
          400: v('--c-gold-400'),
          500: v('--c-gold-500'),
          600: v('--c-gold-600'),
          700: v('--c-gold-700'),
        },
        surface: {
          50: v('--c-surface-50'),
          100: v('--c-surface-100'),
          200: v('--c-surface-200'),
          800: v('--c-surface-800'),
          900: v('--c-surface-900'),
        },
        navy: {
          900: v('--c-navy-900'),
          800: v('--c-navy-800'),
          700: v('--c-navy-700'),
          600: v('--c-navy-600'),
        },
        // Neutral ramp is themed too: in light mode the ramp is inverted
        // (gray-100 = darkest text, gray-700 = subtle border) so existing
        // utility classes keep their semantic meaning without edits.
        gray: {
          100: v('--c-gray-100'),
          200: v('--c-gray-200'),
          300: v('--c-gray-300'),
          400: v('--c-gray-400'),
          500: v('--c-gray-500'),
          600: v('--c-gray-600'),
          700: v('--c-gray-700'),
          800: v('--c-gray-800'),
        },
        // Only the shades used as text / subtle backgrounds are themed;
        // saturated shades (emerald-500/600, red-500/600) keep Tailwind
        // defaults so solid action buttons stay vivid in both themes.
        emerald: {
          400: v('--c-em-400'),
          700: v('--c-em-700'),
          900: v('--c-em-900'),
        },
        red: {
          300: v('--c-red-300'),
          400: v('--c-red-400'),
          700: v('--c-red-700'),
          800: v('--c-red-800'),
          900: v('--c-red-900'),
        },
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', 'sans-serif'],
        mono: ['JetBrains Mono', 'Fira Code', 'monospace'],
      },
    },
  },
  plugins: [],
}
