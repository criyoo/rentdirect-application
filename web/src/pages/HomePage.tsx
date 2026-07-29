import { useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { api, getApiUrl } from '@/lib/api'
import { Listing } from '@/types'
import ListingCard from '@/components/ListingCard'
import { Link } from 'react-router-dom'
import { useAuth } from '@/hooks/useAuth'
import { HiSearch, HiHome, HiLocationMarker, HiBadgeCheck, HiArrowRight, HiShieldCheck, HiCurrencyDollar } from 'react-icons/hi'

const HERO_VIDEO_URL = `${getApiUrl()}/homepage-video`

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
            <section className="relative bg-gradient-to-br from-blue-600 via-blue-700 to-purple-800 overflow-hidden">
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
                                <h3 className="text-2xl text-blue-100 mb-3">Direct from Landlords</h3>
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
                        <div className="grid-modern grid-cols-1 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
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
                        <p className="text-lg text-gray-600 max-w-2xl mx-auto">
                            Experience the future of property rental with our innovative platform
                        </p>
                    </div>

                    <div className="grid-modern grid-cols-1 md:grid-cols-6 lg:grid-cols63 gap-3">
                        <div className="card p-8 text-center hover:shadow-6xl transition-all duration-600">
                            <div className="w-12 h-12 bg-emerald-100 rounded-xl flex items-center justify-center mx-auto mb-4">
                                <HiCurrencyDollar className="w-6 h-6 text-emerald-600" />
                            </div>
                            <h3 className={classNameUSP}>Cost Effecfive</h3>
                            <p className="text-blue-600">
                                Save on unneccessary cost trying to secure or rent a property.
                            </p>
                        </div>

                        <div className="card p-8 text-center hover:shadow-6xl transition-all duration-600">
                            <div className="w-12 h-12 bg-purple-100 rounded-xl flex items-center justify-center mx-auto mb-4">
                                <HiArrowRight className="w-6 h-6 text-purple-600" />
                            </div>
                            <h3 className={classNameUSP}>Direct Contact</h3>
                            <p className="text-blue-600">
                                Bypass the middle man and get direct access to landlords or Tenants
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
                            <h3 className={classNameUSP}>Verified Properties</h3>
                            <p className="text-blue-600">
                                Verified properties listed by trusted landlords with complete transparency.
                            </p>
                        </div>

                        <div className="card p-8 text-center hover:shadow-6xl transition-all duration-600">
                            <div className="w-12 h-12 bg-purple-100 rounded-xl flex items-center justify-center mx-auto mb-4">
                                <HiLocationMarker className="w-6 h-6 text-purple-600" />
                            </div>
                            <h3 className={classNameUSP}>Prime Locations</h3>
                            <p className="text-blue-600">
                                Properties in the most desirable neighborhoods with easy access to amenities.
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

            {/* CTA Section */}
            <section className="section bg-gradient-to-br from-blue-600 to-purple-700">
                <div className="container-modern text-center">
                    <h2 className="text-3xl md:text-4xl font-bold text-white mb-4">
                        Ready to Find Your Dream Home?
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
