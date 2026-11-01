import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { ServicesProvider } from "./services/context";
import { createBackendServices } from "./services/backend";
import "./styles/global.scss";

const services = createBackendServices();

createRoot(document.getElementById("root")!).render(
	<StrictMode>
		<ServicesProvider services={services}>
			<App />
		</ServicesProvider>
	</StrictMode>,
);
