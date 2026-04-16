"use strict";
var __importDefault = (this && this.__importDefault) || function (mod) {
    return (mod && mod.__esModule) ? mod : { "default": mod };
};
Object.defineProperty(exports, "__esModule", { value: true });
const node_path_1 = __importDefault(require("node:path"));
const vite_1 = require("vite");
const plugin_react_1 = __importDefault(require("@vitejs/plugin-react"));
exports.default = (0, vite_1.defineConfig)({
    plugins: [(0, plugin_react_1.default)()],
    // File:// loading in Electron production needs relative asset paths.
    base: "./",
    resolve: {
        alias: {
            "@": node_path_1.default.resolve(__dirname, "src"),
        },
    },
    server: {
        port: 5173,
        strictPort: true,
    },
    build: {
        outDir: "dist",
        emptyOutDir: true,
        sourcemap: true,
    },
});
//# sourceMappingURL=vite.config.js.map