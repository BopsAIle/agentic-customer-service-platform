/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        void: "#0b0f14",
        surface: "#121820",
        border: "#27313d",
        "border-strong": "#3a4654",
        main: "#e8edf3",
        muted: "#8793a3",
        success: "#61d6a7",
        warning: "#e6b65c",
        danger: "#f07878",
        info: "#79aaf7",
      },
      boxShadow: {
        panel: "0 12px 32px rgba(0,0,0,.14)",
      },
    },
  },
  plugins: [],
};
