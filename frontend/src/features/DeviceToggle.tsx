import { IconProp } from "@fortawesome/fontawesome-svg-core";
import { Button } from "../components";
import { DeviceState } from "../model/types";

export interface DeviceToggleProps {
	kind: "camera" | "mic";
	state: DeviceState;
	onClick: () => void;
}

const texts = {
	camera: {
		on: "Камера включена",
		off: "Камера выключена",
		denied: "Нет доступа к камере",
	},
	mic: {
		on: "Микрофон включён",
		off: "Микрофон выключен",
		denied: "Нет доступа к микрофону",
	},
};

const icons: { camera: IconProp[]; mic: IconProp[]; } = {
	camera: ["video", "video-slash"],
	mic: ["microphone", "microphone-slash"],
} as const;

export function DeviceToggle(props: DeviceToggleProps) {
	const { kind, state, onClick } = props;

	return (
		<Button
			variant={state === "on" ? "secondary" : "alert"}
			iconLeft={icons[kind][state === "on" ? 0 : 1]}
			onClick={onClick}
		>
			{texts[kind][state]}
		</Button>
	);
}
