interface BrandLogoProps {
    alt?: string
    className?: string
}

export default function BrandLogo({ alt = 'RentDirect', className = '' }: BrandLogoProps) {
    return (
        <img
            src="/logo_v1.png"
            alt={alt}
            draggable={false}
            onDragStart={(event) => event.preventDefault()}
            className={`object-contain select-none ${className}`}
        />
    )
}
