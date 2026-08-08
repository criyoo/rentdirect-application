import { Link, useNavigate } from 'react-router-dom'
import { HiArrowLeft } from 'react-icons/hi'

type DashboardBackButtonProps = {
    fallbackTo?: string
    to?: string
    label?: string
    className?: string
}

export default function DashboardBackButton({
    fallbackTo = '/',
    to,
    label = 'Back',
    className = '',
}: DashboardBackButtonProps) {
    const navigate = useNavigate()

    const goBack = () => {
        navigate(fallbackTo)
    }

    const buttonClassName = `inline-flex items-center gap-2 rounded-full border border-gray-200 bg-white py-1 pl-1 pr-4 text-sm font-semibold text-gray-700 shadow-sm transition hover:text-blue-700 hover:shadow-md focus:outline-none focus:ring-2 focus:ring-purple-300 ${className}`
    const buttonContent = (
        <>
            <span className="flex h-9 w-9 items-center justify-center rounded-full bg-gradient-to-br from-blue-600 to-purple-600 text-white shadow">
                <HiArrowLeft className="h-5 w-5" />
            </span>
            <span>{label}</span>
        </>
    )

    if (to) {
        return <Link to={to} className={buttonClassName} aria-label={label}>{buttonContent}</Link>
    }

    return (
        <button type="button" onClick={goBack} className={buttonClassName} aria-label={label}>
            {buttonContent}
        </button>
    )
}
