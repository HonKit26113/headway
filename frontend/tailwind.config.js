/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,jsx}",
  ],
  theme: {
    extend: {
      colors: {
        black: '#0B0B0C',
        orange: '#FF5A2E',
        gray: '#8E8C87',
      },
      fontFamily: {
        serif: ['Instrument Serif', 'Georgia', 'serif'],
        sans: ['Geist', 'ui-sans-serif', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
