import type { ReactNode } from "react";
import { FontAwesomeIcon } from "@fortawesome/react-fontawesome";

export interface CheckboxProps {
	checked: boolean;
	onChange: (checked: boolean) => void;
	children: ReactNode;
}

export function Checkbox(props: CheckboxProps) {
	const { checked, onChange, children } = props;

	return (
		<label className="checkbox">
			<input
				type="checkbox"
				checked={checked}
				onChange={(e) => onChange(e.target.checked)}
			/>
			<span className="checkbox__box">
				{checked && <FontAwesomeIcon icon="check" />}
			</span>
			<span className="checkbox__label">{children}</span>
		</label>
	);
}
