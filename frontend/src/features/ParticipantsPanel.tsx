import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { Avatar, Badge, Indicator } from "../components";
import { kindLabel } from "../model/labels";
import type { Participant } from "../model/types";
import { IconProp } from "@fortawesome/fontawesome-svg-core";

export interface ParticipantRowProps {
	participant: Participant;
}

export function ParticipantRow(props: ParticipantRowProps) {
	const { id, name, kind, roleLabel, cameraOn, micOn, speaking } =
		props.participant;

	const state = (
		on: boolean,
		iconOn: IconProp,
		iconOff: IconProp,
		label: string,
	) => (
		<span
			className={on ? "p-row__dev" : "p-row__dev p-row__dev--off"}
			title={`${label}: ${on ? "включено" : "выключено"}`}
		>
			<FontAwesomeIcon icon={on ? iconOn : iconOff} fixedWidth />
		</span>
	);

	return (
		<li className="p-row" data-id={id}>
			<Avatar name={name} />
			<div className="p-row__info">
				<strong>{name}</strong>
				<span>{roleLabel}</span>
				<Badge tone={kind === "ai" ? "tonal" : "neutral"}>
					{kindLabel[kind]}
				</Badge>
			</div>
			{speaking && <Indicator kind="speaking" />}
			{state(cameraOn, "video", "video-slash", "Камера")}
			{state(micOn, "microphone", "microphone-slash", "Микрофон")}
		</li>
	);
}

export interface ParticipantsPanelProps {
	participants: Participant[];
}

export function ParticipantsPanel(props: ParticipantsPanelProps) {
	const { participants } = props;
	return (
		<ul className="p-list">
			{participants.map((p) => (
				<ParticipantRow key={p.id} participant={p} />
			))}
		</ul>
	);
}
