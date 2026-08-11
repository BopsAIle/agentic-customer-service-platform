/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#09111f",
        panel: "#101c2e",
        line: "#24344b",
        mint: "#78e6c4",
        amber: "#f6c66b",
      },
      boxShadow: {
        glow: "0 0 0 1px rgba(120,230,196,.12), 0 24px 70px rgba(0,0,0,.24)",
      },
    },
  },
  plugins: [],
};
