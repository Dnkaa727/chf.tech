import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import type { IconProp } from "@fortawesome/fontawesome-svg-core";
import { classes } from "./classes";

export interface IconButtonProps {
	icon: IconProp;
	label: string;
	variant?: "neutral" | "alert" | "outline" | "primary";
	onClick?: () => void;
	disabled?: boolean;
}
export function IconButton(props: IconButtonProps) {
	const { icon, label, variant = "neutral", onClick, disabled } = props;

	return (
		<button
			type="button"
			className={classes("icon-btn", `icon-btn--${variant}`)}
			aria-label={label}
			title={label}
			onClick={onClick}
			disabled={disabled}
		>
			<FontAwesomeIcon icon={icon} fixedWidth />
		</button>
	);
}
