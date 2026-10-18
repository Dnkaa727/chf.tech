import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { ServicesProvider } from "./services/context";
import { createMockServices } from "./services/mock";
import "./styles/global.scss";

const services = createMockServices();

createRoot(document.getElementById("root")!).render(
	<StrictMode>
		<ServicesProvider services={services}>
			<App />
		</ServicesProvider>
	</StrictMode>,
);
