import { useEffect, useRef, useState } from "react";
import { IconButton, TextField, Badge } from "../components";
import { kindLabel } from "../model/labels";
import { ChatMessage } from "../model/types";
import { classes } from "../components";

const time = (t: number) =>
	new Date(t).toLocaleTimeString("ru-RU", {
		hour: "2-digit",
		minute: "2-digit",
	});

export interface ChatMessageItemProps {
	message: ChatMessage;
	own: boolean;
}

export function ChatMessageItem(props: ChatMessageItemProps) {
	const { message, own } = props;

	return (
		<li className={classes("msg", own && "msg--own")}>
			<div className="msg__meta">
				<strong>{own ? "Вы" : message.authorName}</strong>
				{!own && message.authorKind === "ai" && <Badge>{kindLabel.ai}</Badge>}
				<span>{time(message.sentAt)}</span>
			</div>
			<p className="msg__text">{message.text}</p>
		</li>
	);
}

export interface ChatPanelProps {
	messages: ChatMessage[];
	selfId: string;
	onSend: (text: string) => void;
}

export function ChatPanel(props: ChatPanelProps) {
	const { messages, selfId, onSend } = props;
	const [text, setText] = useState("");
	const end = useRef<HTMLLIElement>(null);

	useEffect(() => {
		end.current?.scrollIntoView({ block: "end" });
	}, [messages.length]);

	const submit = () => {
		const v = text.trim();
		if (v) {
			onSend(v);
			setText("");
		}
	};

	return (
		<>
			<ul className="chat__list">
				{messages.length === 0 && (
					<li className="chat__empty">Сообщений пока нет. Напишите первым.</li>
				)}
				{messages.map((m) => (
					<ChatMessageItem key={m.id} message={m} own={m.authorId === selfId} />
				))}
				<li ref={end} />
			</ul>
			<div className="chat__form">
				<TextField
					id="chat-input"
					value={text}
					onChange={setText}
					placeholder="Сообщение"
					onSubmit={submit}
				/>
				<IconButton
					icon="paper-plane"
					label="Отправить"
					variant="primary"
					onClick={submit}
					disabled={!text.trim()}
				/>
			</div>
		</>
	);
}
