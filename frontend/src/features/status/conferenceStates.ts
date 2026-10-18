import type { ConferenceStatus } from "../../model/types";
import type { StateMessageProps } from "./StateMessage";

export const conferenceStates: Partial<
	Record<ConferenceStatus, Omit<StateMessageProps, "action">>
> = {
	idle: { icon: "spinner", title: "Подготовка", text: "Готовим конференцию." },
	connecting: {
		icon: "spinner",
		title: "Подключение",
		text: "Подключаемся к конференции. Это займёт несколько секунд.",
	},
	waiting: {
		icon: "clock",
		title: "Ожидаем участников",
		text: "Интервьюеры скоро присоединятся. Оставайтесь на странице.",
	},
	reconnecting: {
		icon: "plug-circle-exclamation",
		title: "Соединение потеряно",
		text: "Восстанавливаем соединение. Не закрывайте страницу.",
	},
	ended: {
		icon: "flag-checkered",
		title: "Конференция завершена",
		text: "Собеседование закончено.",
	},
};
