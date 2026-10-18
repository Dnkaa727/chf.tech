import type { ReactNode } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";
import { Indicator } from "./Indicator";
import { classes } from "./classes";
import { IconProp } from "@fortawesome/fontawesome-svg-core";

export interface ButtonProps {
	variant?: "primary" | "secondary" | "tonal" | "danger" | "alert";
	size?: "m" | "l";
	children: ReactNode;
	onClick?: () => void;
	disabled?: boolean;
	iconLeft?: IconProp;
	iconRight?: IconProp;
	fullWidth?: boolean;
	count?: number;
	collapseOnMobile?: boolean;
}

export function Button(props: ButtonProps) {
	const {
		variant = "primary",
		size = "m",
		children,
		onClick,
		disabled,
		iconLeft,
		iconRight,
		fullWidth,
		count,
		collapseOnMobile,
	} = props;

	return (
		<button
			type="button"
			disabled={disabled}
			onClick={onClick}
			className={classes(
				"btn",
				`btn--${variant}`,
				`btn--${size}`,
				fullWidth && "btn--full",
				collapseOnMobile && "btn--collapse",
			)}
		>
			{iconLeft && <FontAwesomeIcon icon={iconLeft} fixedWidth />}
			<span className="btn__text">{children}</span>
			{iconRight && <FontAwesomeIcon icon={iconRight} className="btn__right" />}
			{!!count && <Indicator kind="count" count={count} />}
		</button>
	);
}
