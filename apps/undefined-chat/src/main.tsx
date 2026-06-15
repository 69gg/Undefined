import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { LanguageProvider } from "./i18n";
import { PlatformProvider } from "./platform/PlatformContext";
import "./styles.css";

const root = document.getElementById("root");

if (!root) {
	throw new Error("Missing root element");
}

createRoot(root).render(
	<StrictMode>
		<PlatformProvider>
			<LanguageProvider>
				<App />
			</LanguageProvider>
		</PlatformProvider>
	</StrictMode>,
);
