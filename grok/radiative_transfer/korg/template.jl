using Korg

function synthesize(atmosphere_path, linelist_path, metallicity)
    println("Running with ", atmosphere_path, " and ", linelist_path)
    atm = Korg.read_model_atmosphere(atmosphere_path)
    linelist = Korg.read_linelist(linelist_path)
    println("Synthesizing..")
    @time spectrum = Korg.synthesize(atm, linelist, {lambda_vacuum_min}:0.01:{lambda_vacuum_max}; metallicity=metallicity)
    println("Done")
    return spectrum
end

println("Going once..)
@time spectrum = synthesize({atmosphere_path}, {linelist_path}, {metallicity:.2f})

println("Going twice..)
@time spectrum = synthesize({atmosphere_path}, {linelist_path}, {metallicity:.2f})

# Save to disk.
with open("spectrum.out", "w") do fp:
    for flux in spectrum.flux
        println(fp, flux)
    end
end