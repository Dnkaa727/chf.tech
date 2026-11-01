import { createStore } from "../store";
import { createBrowserMediaService } from "../media/browserMedia";
import type { Services } from "../types";
import type {
	ChatMessage,
	ConferenceNotice,
	ConferenceState,
	Participant,
	StageContent,
} from "../../model/types";
import { SELF_ID } from "../../model/types";

const slide = `<svg xmlns="http://www.w3.org/2000/svg" width="960" height="540"><rect width="960" height="540" fill="#fff"/><rect x="60" y="60" width="840" height="420" rx="28" fill="#E4ECFD"/><text x="100" y="200" font-family="sans-serif" font-size="48" font-weight="700" fill="#0A2896">О компании</text><text x="100" y="270" font-family="sans-serif" font-size="28" fill="#6B7491">Команда 240 человек, 12 направлений</text><rect x="100" y="330" width="200" height="90" rx="16" fill="#3063EB"/><rect x="330" y="330" width="200" height="90" rx="16" fill="#fff"/></svg>`;

const slideSrc = `data:image/svg+xml;utf8,${encodeURIComponent(slide)}`;

const person = (
	id: string,
	name: string,
	kind: Participant["kind"],
	roleLabel: string,
): Participant => ({
	id,
	name,
	kind,
	roleLabel,
	cameraOn: true,
	micOn: true,
	speaking: false,
});

const script: { who: Participant; text: string }[] = [
	{
		who: person("ai-1", "Анна", "ai", ""),
		text: "Здравствуйте! Начнём с короткого знакомства.",
	},
	{
		who: person("ai-2", "Макс", "ai", ""),
		text: "Подготовил вопросы по вашему опыту работы с React.",
	},
	{
		who: person("h-1", "Ирина Орлова", "human", ""),
		text: "Я наблюдаю за беседой, можете не обращать внимания.",
	},
	{
		who: person("ai-1", "Анна", "ai", ""),
		text: "Расскажите о проекте, которым вы гордитесь.",
	},
];

export function createMockServices(): Services {
	const media = createBrowserMediaService();
	const state = createStore<ConferenceState>({ status: "idle" });
	const events = createStore<ConferenceNotice | null>(null);
	const list = createStore<Participant[]>([]);
	const content = createStore<Record<string, StageContent>>({});
	const messages = createStore<ChatMessage[]>([]);
	let timers: number[] = [];
	let myName = "Вы";

	const me = person(SELF_ID, "Вы", "candidate", "Кандидат");
	const ai1 = person("ai-1", "Анна", "ai", "ИИ-интервьюер, знакомство");
	const ai2 = person("ai-2", "Макс", "ai", "ИИ-интервьюер, техническая часть");
	const hr = person("h-1", "Ирина Орлова", "human", "Представитель компании");

	const later = (ms: number, fn: () => void) => {
		timers.push(window.setTimeout(fn, ms));
	};

	const every = (ms: number, fn: () => void) => {
		timers.push(window.setInterval(fn, ms));
	};

	const stop = () => {
		timers.forEach((t) => window.clearInterval(t));
		timers = [];
	};

	const notify = (text: string) =>
		events.set({ id: Date.now() + Math.random(), text });

	const has = (id: string) => list.get().some((p) => p.id === id);

	const add = (p: Participant) => {
		if (!has(p.id)) {
			list.set([...list.get(), p]);
			notify(`${p.name} вошёл в конференцию`);
		}
	};

	const remove = (id: string) => {
		const p = list.get().find((x) => x.id === id);
		if (p) {
			list.set(list.get().filter((x) => x.id !== id));
			notify(`${p.name} вышел из конференции`);
		}
	};

	const say = (id: string) =>
		list.set(list.get().map((p) => ({ ...p, speaking: p.id === id })));

	const push = (who: Participant, text: string) => {
		const name = who.id === SELF_ID ? myName : who.name;
		messages.set([
			...messages.get(),
			{
				id: `${Date.now()}${Math.random()}`,
				authorId: who.id,
				authorName: name,
				authorKind: who.kind,
				text,
				sentAt: Date.now(),
			},
		]);
	};

	return {
		media,
		participants: { list, content },
		conference: {
			state,
			events,
			async join(name) {
				stop();
				myName = name;
				messages.set([]);
				list.set([{ ...me, name }]);
				content.set({
					[SELF_ID]: { type: "avatar" },
					"ai-1": { type: "avatar" },
					"ai-2": { type: "visualizer", level: 0 },
					"h-1": { type: "image", src: slideSrc },
				});
				state.set({ status: "connecting" });
				later(1500, () => state.set({ status: "waiting" }));
				later(3000, () => {
					add(ai1);
					state.set({ status: "live" });
				});
				later(4000, () => add(ai2));
				later(5500, () => add(hr));
				const order = ["ai-1", SELF_ID, "ai-2", "h-1"];
				let i = 0;
				later(3500, () => {
					say("ai-1");
					every(4500, () => {
						i = (i + 1) % order.length;
						if (has(order[i])) say(order[i]);
					});
				});
				every(150, () => {
					if (list.get().find((p) => p.speaking)?.id === "ai-2")
						content.set({
							...content.get(),
							"ai-2": { type: "visualizer", level: Math.random() },
						});
				});
				script.forEach((m, k) =>
					later(6000 + k * 9000, () => push(m.who, m.text)),
				);
				later(32000, () => remove("h-1"));
				later(42000, () => add(hr));
				later(55000, () => {
					state.set({ status: "reconnecting" });
					later(3500, () => {
						state.set({ status: "live" });
						notify("Соединение восстановлено");
					});
				});
			},
			async leave() {
				stop();
				state.set({ status: "ended" });
			},
		},
		chat: {
            interviewerTyping: createStore(false),
			messages,
			async send(text) {
				push(me, text);
				later(1500, () => push(ai1, "Принято, спасибо."));
			},
		},
	};
}
