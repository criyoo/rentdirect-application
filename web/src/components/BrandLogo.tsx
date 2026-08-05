interface BrandLogoProps {
    alt?: string
    className?: string
}

export default function BrandLogo({ alt = 'RentDirect', className = '' }: BrandLogoProps) {
    return (
        <img
            src="/logo.png"
            alt={alt}
            className={`object-contain ${className}`}
        />
    )
}
