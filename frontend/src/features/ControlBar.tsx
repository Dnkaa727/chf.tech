import { IconProp } from "@fortawesome/fontawesome-svg-core";
import {
	Button,
	IconButton,
	type ButtonProps,
	type IconButtonProps,
} from "../components";

export interface ControlAction {
	id: string;
	icon: IconProp;
	label: string;
	onClick: () => void;
	text?: string;
	count?: number;
	iconVariant?: IconButtonProps["variant"];
	buttonVariant?: ButtonProps["variant"];
}

export interface ControlBarProps {
	left: ControlAction[];
	center: ControlAction[];
	right: ControlAction[];
}

function Action(props: { action: ControlAction }) {
	const { id, icon, label, onClick, text, count, iconVariant, buttonVariant } =
		props.action;

	return text ? (
		<Button
			variant={buttonVariant}
			iconLeft={icon}
			count={count}
			onClick={onClick}
			collapseOnMobile
		>
			{text}
		</Button>
	) : (
		<IconButton
			icon={icon}
			label={label}
			variant={iconVariant}
			onClick={onClick}
		/>
	);
}

export function ControlBar(props: ControlBarProps) {
	const { left, center, right } = props;

	const group = (items: ControlAction[], cls: string) => (
		<div className={`control-bar__group ${cls}`}>
			{items.map((a) => (
				<Action key={a.id} action={a} />
			))}
		</div>
	);

	return (
		<nav className="control-bar" aria-label="Управление">
			{group(left, "control-bar__group--start")}
			{group(center, "")}
			{group(right, "control-bar__group--end")}
		</nav>
	);
}
