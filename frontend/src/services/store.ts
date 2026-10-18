export interface Readable<T> {
	get(): T;
	subscribe(listener: (value: T) => void): () => void;
}

export interface Store<T> extends Readable<T> {
	set(value: T): void;
}

export function createStore<T>(initial: T): Store<T> {
	let value = initial;
	const listeners = new Set<(v: T) => void>();
	return {
		get: () => value,
		set(next) {
			value = next;
			listeners.forEach((l) => l(next));
		},
		subscribe(l) {
			listeners.add(l);
			return () => {
				listeners.delete(l);
			};
		},
	};
}
