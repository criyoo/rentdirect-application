import { useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, getApiUrl } from '@/lib/api'
import { Listing } from '@/types'
import ListingCard from '@/components/ListingCard'
import { Link } from 'react-router-dom'
import { useAuth } from '@/hooks/useAuth'
import { HiSearch, HiHome, HiLocationMarker, HiBadgeCheck, HiArrowRight, HiShieldCheck, HiCurrencyDollar, HiCheck } from 'react-icons/hi'

const HERO_VIDEO_URL = `${getApiUrl()}/homepage-video`

const subscriptionPlans = [
    {
        badge: 'Start here',
        name: 'Bronze',
        summary: 'The essentials for exploring RentDirect.',
        features: [
            'Browse verified properties',
            'Save homes to your favourites',
            'View landlord profiles',
            'Access support and feedback tools',
        ],
    },
    {
        badge: 'Most popular',
        name: 'Silver',
        summary: 'Everything you need to move from search to rental.',
        features: [
            'Contact landlords directly',
            'Arrange property viewings',
            'Track rental progress',
            'See property locations and maps',
        ],
        highlight: true,
    },
    {
        badge: 'More flexibility',
        name: 'Gold',
        summary: 'Extra visibility and support for a smoother experience.',
        features: [
            'Access the community chat',
            'Review landlords and properties',
            'Priority issue handling',
            'See property verification badges',
        ],
    },
    {
        badge: 'Full access',
        name: 'Platinum',
        summary: 'The complete RentDirect experience for confident decisions.',
        features: [
            'Premium rental workflow support',
            'Deeper verification visibility',
            'High-confidence verification insights',
            'Faster support response times',
        ],
    },
]

export default function HomePage() {
    const { user } = useAuth()
    const heroVideoRef = useRef<HTMLVideoElement | null>(null)
    const { data: featured } = useQuery({
        queryKey: ['listings', 'featured'],
        queryFn: async () => (await api.get<any[]>('/featured/listings')).data
    })
    const { data: favourites = [] } = useQuery({
        queryKey: ['me', 'favourites'],
        enabled: user?.role === 'tenant',
        queryFn: async () => (await api.get<Listing[]>('/users/me/favourites')).data,
    })
    const { data: publicStats } = useQuery({
        queryKey: ['users', 'public-stats'],
        queryFn: async () => (await api.get<{ properties: number; landlords: number; tenants: number }>('/users/public-stats')).data
    })
    const favouriteIds = new Set(favourites.map((listing) => listing.id))

    const classNameUSP = "text-lg font-semibold text-gray-900 mb-3"

    useEffect(() => {
        if (!heroVideoRef.current) return
        heroVideoRef.current.playbackRate = 0.40
    }, [])

    return (
        <div className="min-h-screen">
            {/* Hero Section */}
            <section className="relative overflow-hidden rounded-bl-[3rem] rounded-br-[3rem] bg-gradient-to-br from-blue-600 via-blue-700 to-purple-800">
                {/* Background Pattern */}
                <div className="absolute inset-0 bg-black/10">
                    <div className="absolute inset-0 opacity-20" style={{
                        backgroundImage: `url("data:image/svg+xml,%3Csvg width='60' height='60' viewBox='0 0 60 60' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='none' fill-rule='evenodd'%3E%3Cg fill='%23ffffff' fill-opacity='0.05'%3E%3Ccircle cx='30' cy='30' r='2'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E")`
                    }}></div>
                </div>

                <div className="container-modern relative z-10">
                    <div className="section">
                        <div className="grid lg:grid-cols-2 gap-12 items-center">
                            {/* Hero Content */}
                            <div className="text-center lg:text-left">
                                <h1 className="text-4xl md:text-5xl lg:text-6xl font-bold text-white mb-8 leading-tight">
                                    Find Your Perfect
                                    <span className="block bg-gradient-to-r from-yellow-400 to-orange-400 bg-clip-text text-transparent">
                                        Home Today
                                    </span>
                                </h1>
                                <h3 className="text-4xl text-blue-100 mb-3">No agents. No middleman.</h3>
                                <p className="text-xl text-blue-100 mb-8 max-w-2xl">
                                    Discover thousands of verified properties from trusted landlords.
                                    Direct communication, transparent pricing, and seamless rental experience.
                                </p>

                                <div className="flex flex-col sm:flex-row gap-4 justify-center lg:justify-start">
                                    <Link
                                        to="/search"
                                        className="btn btn-primary text-lg px-8 py-4 shadow-lg hover:shadow-xl transform hover:-translate-y-1 transition-all duration-200"
                                    >
                                        <HiSearch className="w-5 h-5 mr-2" />
                                        Search Properties
                                    </Link>
                                    {user && user.role === 'landlord' && (
                                        <Link
                                            to="/listings/new"
                                            className="btn btn-outline text-lg px-8 py-4 border-white text-white hover:bg-white hover:text-blue-600 shadow-lg hover:shadow-xl transform hover:-translate-y-1 transition-all duration-200"
                                        >
                                            <HiHome className="w-5 h-5 mr-2" />
                                            List Your Property
                                        </Link>
                                    )}
                                </div>

                                {/* Login/Register Menu for Non-Authenticated Users */}
                                {!user && (
                                    <div className="mt-6 flex flex-col sm:flex-row gap-3 justify-center lg:justify-start">
                                        <Link
                                            to="/login"
                                            className="inline-flex items-center px-6 py-3 border-2 border-white/30 text-white hover:bg-white hover:text-blue-600 rounded-lg font-medium transition-all duration-200 hover:border-white"
                                        >
                                            Sign In
                                        </Link>
                                        <Link
                                            to="/register"
                                            className="inline-flex items-center px-6 py-3 bg-white text-blue-600 hover:bg-blue-50 rounded-lg font-medium transition-all duration-200 shadow-lg hover:shadow-xl"
                                        >
                                            Create Account
                                        </Link>
                                    </div>
                                )}

                                {/* Stats */}
                                <div className="grid grid-cols-3 gap-6 mt-12 pt-8 border-t border-white/20">
                                    <div className="text-center">
                                        <div className="text-2xl font-bold text-white">{publicStats?.properties ?? 0}</div>
                                        <div className="text-blue-200 text-sm">Properties</div>
                                    </div>
                                    <div className="text-center">
                                        <div className="text-2xl font-bold text-white">{publicStats?.landlords ?? 0}</div>
                                        <div className="text-blue-200 text-sm">Landlords</div>
                                    </div>
                                    <div className="text-center">
                                        <div className="text-2xl font-bold text-white">{publicStats?.tenants ?? 0}</div>
                                        <div className="text-blue-200 text-sm">Happy Tenants</div>
                                    </div>
                                </div>
                            </div>

                            {/* Hero Visual */}
                            <div className="relative">
                                <div className="relative bg-white/10 backdrop-blur-sm rounded-2xl p-8 shadow-2xl">
                                    <div className="aspect-video overflow-hidden rounded-xl mb-6 bg-black/30 ring-1 ring-white/10">
                                        <video
                                            ref={heroVideoRef}
                                            className="h-full w-full object-cover"
                                            autoPlay
                                            loop
                                            muted
                                            playsInline
                                            preload="auto"
                                        >
                                            <source src={HERO_VIDEO_URL} type="video/mp4" />
                                        </video>
                                    </div>
                                    <div className="space-y-4">
                                        <div className="flex items-center space-x-3">
                                            <div className="w-3 h-3 bg-green-400 rounded-full"></div>
                                            <span className="text-white/90">Verified tenants, landlord and properties</span>
                                        </div>
                                        <div className="flex items-center space-x-3">
                                            <div className="w-3 h-3 bg-blue-400 rounded-full"></div>
                                            <span className="text-white/90">Direct landlord & tenant communication</span>
                                        </div>
                                        <div className="flex items-center space-x-3">
                                            <div className="w-3 h-3 bg-purple-400 rounded-full"></div>
                                            <span className="text-white/90">Secure and transparent payments</span>
                                        </div>
                                        <div className="flex items-center space-x-3">
                                            <div className="w-3 h-3 bg-red-400 rounded-full"></div>
                                            <span className="text-white/90">Low cost with no hidden fees</span>
                                        </div>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </section>

            {/* Featured Properties Section */}
            <section className="section bg-gray-50">
                <div className="mx-auto flex max-w-[100rem] flex-col gap-2 px-4 sm:px-6 lg:px-8">
                    <div className="text-center mb-4">
                        <h2 className="text-3xl md:text-4xl font-bold text-gray-900 mb-4">
                            Featured Properties
                        </h2>
                        <p className="text-lg text-gray-600 max-w-2xl mx-auto">
                            Discover our handpicked selection of premium properties in prime locations
                        </p>
                    </div>

                    {featured && featured.length > 0 ? (
                        <div className="grid-modern grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-3 gap-4">
                            {featured.map((listing: Listing) => (
                                <div key={listing.id} className="animate-fade-in">
                                    <ListingCard listing={listing} isFavourite={favouriteIds.has(listing.id)} />
                                </div>
                            ))}
                        </div>
                    ) : (
                        <div className="text-center py-12">
                            <div className="w-16 h-16 bg-gray-200 rounded-full flex items-center justify-center mx-auto mb-4">
                                <HiHome className="w-8 h-8 text-gray-400" />
                            </div>
                            <h3 className="text-lg font-medium text-gray-900 mb-2">No featured properties yet</h3>
                            <p className="text-gray-600 mb-6">Check back soon for amazing properties!</p>
                            <Link to="/search" className="btn btn-primary">
                                Browse All Properties
                            </Link>
                        </div>
                    )}

                    <div className="text-center mt-12">
                        <Link
                            to="/search"
                            className="btn btn-outline text-lg px-8 py-3 group"
                        >
                            View All Properties
                            <HiArrowRight className="w-5 h-5 ml-2 group-hover:translate-x-1 transition-transform duration-200" />
                        </Link>
                    </div>
                </div>
            </section>

            {/* Features Section */}
            <section className="section bg-white">
                <div className="container-modern">
                    <div className="text-center mb-12">
                        <h2 className="text-2xl md:text-4xl font-bold text-blue-700 mb-4">
                            Why Choose RentDirect?
                        </h2>
                        <p className="text-4xl text-gray-900 max-w-2xl mx-auto">
                            A smarter way to rent in Nigeria
                        </p>
                        <p className="text-lg text-gray-600 max-w-2xl mx-auto">
                            We've built a platform that cuts out agent fees, makes payments transparent, and puts tenants and landlords in direct contact.
                        </p>
                    </div>

                    <div className="grid-modern grid-cols-1 md:grid-cols-6 lg:grid-cols63 gap-3">
                        <div className="card p-8 text-center hover:shadow-6xl transition-all duration-600">
                            <div className="w-12 h-12 bg-emerald-100 rounded-xl flex items-center justify-center mx-auto mb-4">
                                <HiCurrencyDollar className="w-6 h-6 text-emerald-600" />
                            </div>
                            <h3 className={classNameUSP}>Cost Effecfive</h3>
                            <p className="text-blue-600">
                                Connect directly with landlords and skip the 20–30% agent commission.
                            </p>
                        </div>

                        <div className="card p-8 text-center hover:shadow-6xl transition-all duration-600">
                            <div className="w-12 h-12 bg-purple-100 rounded-xl flex items-center justify-center mx-auto mb-4">
                                <HiArrowRight className="w-6 h-6 text-purple-600" />
                            </div>
                            <h3 className={classNameUSP}>In-App Chat</h3>
                            <p className="text-blue-600">
                                Negotiate, ask questions, and arrange viewings through our secure messenger.
                            </p>
                        </div>

                        <div className="card p-8 text-center hover:shadow-6xl transition-all duration-600">
                            <div className="w-12 h-12 bg-indigo-100 rounded-xl flex items-center justify-center mx-auto mb-4">
                                <HiSearch className="w-6 h-6 text-indigo-600" />
                            </div>
                            <h3 className={classNameUSP}>Efficient Tracking</h3>
                            <p className="text-blue-600">
                                Track every transaction including rentals progress and payments.
                            </p>
                        </div>

                        <div className="card p-8 text-center hover:shadow-6xl transition-all duration-600">
                            <div className="w-12 h-12 bg-green-100 rounded-xl flex items-center justify-center mx-auto mb-4">
                                <HiBadgeCheck className="w-6 h-6 text-green-600" />
                            </div>
                            <h3 className={classNameUSP}>Verified Listings</h3>
                            <p className="text-blue-600">
                                Every listing is reviewed by our admin team for your peace of mind.
                            </p>
                        </div>

                        <div className="card p-8 text-center hover:shadow-6xl transition-all duration-600">
                            <div className="w-12 h-12 bg-purple-100 rounded-xl flex items-center justify-center mx-auto mb-4">
                                <HiLocationMarker className="w-6 h-6 text-purple-600" />
                            </div>
                            <h3 className={classNameUSP}>Seamless Payments</h3>
                            <p className="text-blue-600">
                                Pay annual rent, deposits, and caution fees securely within the platform.
                            </p>
                        </div>

                        <div className="card p-8 text-center hover:shadow-6xl transition-all duration-200">
                            <div className="w-12 h-12 bg-blue-100 rounded-xl flex items-center justify-center mx-auto mb-4">
                                <HiShieldCheck className="w-6 h-6 text-blue-600" />
                            </div>
                            <h3 className={classNameUSP}>Quality Experience</h3>
                            <p className="text-blue-600">
                                Avoid scams and deal with high quality & verified Landlords and Tenants
                            </p>
                        </div>
                    </div>
                </div>
            </section>



            {/* Subscription Plans Section */}
            <section className="relative overflow-hidden bg-slate-50 py-20 md:py-28">
                <div className="pointer-events-none absolute -left-24 top-10 h-72 w-72 rounded-full bg-orange-200/50 blur-3xl" />
                <div className="pointer-events-none absolute -right-24 bottom-0 h-80 w-80 rounded-full bg-blue-200/60 blur-3xl" />

                <div className="relative mx-auto max-w-[100rem] px-4 sm:px-6 lg:px-8">
                    <div className="mx-auto max-w-3xl text-center">
                        <p className="mb-4 text-sm font-bold uppercase tracking-[0.24em] text-orange-500">
                            Simple pricing, your way
                        </p>
                        <h2 className="text-3xl font-bold tracking-tight text-slate-950 md:text-5xl">
                            Pay only for what you need
                        </h2>
                        <p className="mx-auto mt-6 max-w-2xl text-lg leading-8 text-slate-600">
                            Transparent fees with no hidden charges. No agent commissions — ever.
                        </p>
                    </div>

                    <div className="mt-14 grid gap-5 md:grid-cols-2 xl:grid-cols-4">
                        {subscriptionPlans.map((plan) => (
                            <article
                                key={plan.name}
                                className={`relative flex h-full flex-col rounded-[2rem] border p-7 shadow-sm transition-all duration-200 hover:-translate-y-1 hover:shadow-xl ${plan.highlight
                                    ? 'border-slate-950 bg-slate-950 text-white shadow-slate-950/20'
                                    : 'border-slate-200 bg-white text-slate-950'
                                    }`}
                            >
                                <div className="flex items-center justify-between gap-3">
                                    <span className={`rounded-full px-3 py-1 text-xs font-bold uppercase tracking-[0.16em] ${plan.highlight
                                        ? 'bg-orange-400 text-slate-950'
                                        : 'bg-orange-50 text-orange-600'
                                        }`}>
                                        {plan.badge}
                                    </span>
                                    {plan.highlight && <HiBadgeCheck className="h-6 w-6 text-orange-400" />}
                                </div>

                                <h3 className={`mt-8 text-3xl font-bold ${plan.highlight ? 'text-white' : 'text-slate-950'}`}>
                                    {plan.name}
                                </h3>
                                <p className={`mt-3 min-h-14 text-sm leading-6 ${plan.highlight ? 'text-slate-300' : 'text-slate-600'}`}>
                                    {plan.summary}
                                </p>

                                <ul className="mt-8 flex-1 space-y-4">
                                    {plan.features.map((feature) => (
                                        <li key={feature} className="flex items-start gap-3 text-sm leading-5">
                                            <span className={`mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full ${plan.highlight
                                                ? 'bg-orange-400 text-slate-950'
                                                : 'bg-slate-100 text-blue-600'
                                                }`}>
                                                <HiCheck className="h-3.5 w-3.5" />
                                            </span>
                                            <span className={plan.highlight ? 'text-slate-200' : 'text-slate-700'}>{feature}</span>
                                        </li>
                                    ))}
                                </ul>

                                <Link
                                    to={user ? '/billing' : '/register'}
                                    className={`mt-10 inline-flex items-center justify-center gap-2 rounded-xl px-5 py-3 text-sm font-bold transition-colors ${plan.highlight
                                        ? 'bg-white text-slate-950 hover:bg-orange-50'
                                        : 'bg-slate-950 text-white hover:bg-blue-700'
                                        }`}
                                >
                                    {user ? 'View your options' : 'Get started'}
                                    <HiArrowRight className="h-4 w-4" />
                                </Link>
                            </article>
                        ))}
                    </div>
                </div>
            </section>

            {/* CTA Section */}
            <section className="section relative -mt-12 overflow-hidden bg-[linear-gradient(180deg,#f8fafc_0%,#f8fafc_9%,#dbe3f8_22%,#2563eb_48%,#7e22ce_100%)] pt-32 md:-mt-20 md:pt-40">
                <div className="container-modern relative z-10 text-center">
                    <h2 className="text-3xl md:text-4xl font-bold text-white mb-4">
                        Ready to Find Your Next Space?
                    </h2>
                    <p className="text-xl text-blue-100 mb-8 max-w-2xl mx-auto">
                        Join thousands of satisfied tenants who found their perfect home on RentDirect
                    </p>
                    <div className="flex flex-col sm:flex-row gap-4 justify-center">
                        <Link
                            to="/search"
                            className="btn btn-primary text-lg px-8 py-4 bg-white text-blue-600 hover:bg-gray-100"
                        >
                            Start Searching
                        </Link>
                        {!user && (
                            <Link
                                to="/register"
                                className="btn btn-outline text-lg px-8 py-4 border-white text-white hover:bg-white hover:text-blue-600"
                            >
                                Create Account
                            </Link>
                        )}
                    </div>
                </div>
            </section>
        </div>
    )
}
