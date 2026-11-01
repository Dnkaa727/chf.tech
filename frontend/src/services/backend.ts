import { createBrowserMediaService } from "./media/browserMedia";
import { createStore } from "./store";
import type { Services } from "./types";
import type {
	ChatMessage,
	ConferenceNotice,
	ConferenceState,
	Participant,
	StageContent,
} from "../model/types";
import { SELF_ID } from "../model/types";

type BackendSnapshot = {
	conferenceId: string;
	state: ConferenceState;
	participants: Participant[];
	content: Record<string, StageContent>;
	interviewerTyping: boolean;
	messages: ChatMessage[];
	session: {
		sessionId: string;
		cardId: string;
		status: string;
		pendingQuestion: string | null;
		followupsAsked: number;
	};
};

const API_URL = import.meta.env.VITE_BACKEND_URL ?? "http://127.0.0.1:8081";

const WS_URL = API_URL.replace(/^http/, "ws");

async function request<T>(path: string, init?: RequestInit): Promise<T> {
	const response = await fetch(`${API_URL}${path}`, {
		...init,
		headers: {
			"Content-Type": "application/json",
			...(init?.headers ?? {}),
		},
	});

	if (!response.ok) {
		let detail = `Backend request failed: ${response.status}`;

		try {
			const body = await response.json();

			if (typeof body.detail?.message === "string") detail = body.detail.message;
            if (typeof body.detail === "string") {
				detail = body.detail;
			}
		} catch {}

		throw new Error(detail);
	}

	return response.json() as Promise<T>;
}

function applySnapshot(
	next: BackendSnapshot,
	state: ReturnType<typeof createStore<ConferenceState>>,
	list: ReturnType<typeof createStore<Participant[]>>,
	content: ReturnType<typeof createStore<Record<string, StageContent>>>,
	messages: ReturnType<typeof createStore<ChatMessage[]>>,
	typing: ReturnType<typeof createStore<boolean>>,
) {
	state.set(next.state);
	list.set(next.participants);
	content.set(next.content);
	messages.set(next.messages.map(message => ({
		...message,
		audioUrl: message.authorKind === "ai"
			? `${API_URL}/api/conferences/${encodeURIComponent(next.conferenceId)}/messages/${encodeURIComponent(message.id)}/audio`
			: undefined,
	})));
	typing.set(next.interviewerTyping);
}

export function createBackendServices(): Services {
	const media = createBrowserMediaService();

	const state = createStore<ConferenceState>({
		status: "idle",
	});

	const interviewerTyping = createStore(false);

	const events = createStore<ConferenceNotice | null>(null);
	const list = createStore<Participant[]>([]);
	const content = createStore<Record<string, StageContent>>({});
	const messages = createStore<ChatMessage[]>([]);

	let conferenceId: string | null = null;
	let socket: WebSocket | null = null;
	let lastNotifiedMessageId: string | null = null;

	const notifyLatestMessage = (next: BackendSnapshot) => {
		const latest = next.messages[next.messages.length - 1];

		if (!latest || latest.id === lastNotifiedMessageId) {
			return;
		}

		lastNotifiedMessageId = latest.id;

		if (latest.authorId !== SELF_ID) {
			events.set({
				id: Date.now(),
				text: `${latest.authorName}: ${latest.text}`,
			});
		}
	};

	const applyBackendSnapshot = (next: BackendSnapshot) => {
		applySnapshot(next, state, list, content, messages, interviewerTyping);

		notifyLatestMessage(next);
	};

	const closeSocket = () => {
		if (socket) {
			socket.onclose = null;
			socket.close();
			socket = null;
		}
	};

	return {
		media,

		participants: {
			list,
			content,
		},

		conference: {
			state,
			events,

			async join(name: string) {
				closeSocket();

				state.set({
					status: "connecting",
				});

				const next = await request<BackendSnapshot>(
					"/api/conferences",
					{
						method: "POST",
						body: JSON.stringify({
							name,
							card_id:
								import.meta.env.VITE_INTERVIEW_CARD_ID ??
								undefined,
						}),
					},
				);

				conferenceId = next.conferenceId;
				lastNotifiedMessageId = null;

				applyBackendSnapshot(next);

				socket = new WebSocket(
					`${WS_URL}/api/conferences/${conferenceId}/ws`,
				);

				socket.onmessage = (event) => {
					try {
						const update = JSON.parse(
							event.data,
						) as BackendSnapshot;

						applyBackendSnapshot(update);
					} catch {
						events.set({
							id: Date.now(),
							text: "Сервер прислал некорректное состояние",
						});
					}
				};

				socket.onerror = () => {
					events.set({
						id: Date.now(),
						text: "Соединение с сервером потеряно",
					});
				};

				socket.onclose = () => {
					if (state.get().status !== "ended") {
						events.set({
							id: Date.now(),
							text: "WebSocket-соединение закрыто",
						});
					}
				};
			},

			async leave() {
				closeSocket();

				if (conferenceId) {
					await request<BackendSnapshot>(
						`/api/conferences/${conferenceId}`,
						{
							method: "DELETE",
						},
					);
				}

				conferenceId = null;
				state.set({
                    ...state.get(),
					status: "ended",
				});
			},
		},

		chat: {
			messages,
			interviewerTyping,

			async send(text: string) {
				if (!conferenceId) {
					throw new Error("Conference is not connected");
				}

				const next = await request<BackendSnapshot>(
					`/api/conferences/${conferenceId}/messages`,
					{
						method: "POST",
						body: JSON.stringify({ text }),
					},
				);
                applyBackendSnapshot(next);
			},
		},
	};
}
