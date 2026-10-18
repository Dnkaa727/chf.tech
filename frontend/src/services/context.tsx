import { createContext, useContext, type ReactNode } from "react";
import type { Services } from "./types";

const ServicesContext = createContext<Services | null>(null);

export interface ServicesProviderProps {
	services: Services;
	children: ReactNode;
}

export function ServicesProvider(props: ServicesProviderProps) {
	const { services, children } = props;
	return (
		<ServicesContext.Provider value={services}>
			{children}
		</ServicesContext.Provider>
	);
}

export function useServices(): Services {
	const s = useContext(ServicesContext);
	if (!s) throw new Error("ServicesProvider не найден");
	return s;
}
