import { useSyncExternalStore } from "react";
import type { Readable } from "../services/store";

export function useReadable<T>(source: Readable<T>): T {
	return useSyncExternalStore(source.subscribe, source.get);
}
