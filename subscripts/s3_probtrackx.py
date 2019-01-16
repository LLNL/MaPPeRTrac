#!/usr/bin/env python3
from os.path import join,exists
from subscripts.utilities import write,smart_remove
from parsl.app.app import python_app

@python_app(executors=['s3'], cache=True)
def s3_1_start(params, inputs=[]):
    from subscripts.utilities import record_start
    use_gpu = params['use_gpu']
    stdout = params['stdout']
    record_start(params)
    if use_gpu:
        write(stdout, "Running Probtrackx with GPU")
    else:
        write(stdout, "Running Probtrackx without GPU")

@python_app(executors=['s3'], cache=True)
def s3_2_probtrackx(params, a, b, inputs=[]):
    import time
    from subscripts.utilities import run,smart_remove,smart_mkdir,write,is_float,is_integer,record_start,record_apptime
    from os.path import join,exists,split
    from shutil import copyfile
    sdir = params['sdir']
    stdout = params['stdout']
    container = params['container']
    use_gpu = params['use_gpu']
    start_time = time.time()
    EDI_allvols = join(sdir,"EDI","allvols")
    a_file = join(EDI_allvols, a + "_s2fa.nii.gz")
    b_file = join(EDI_allvols, b + "_s2fa.nii.gz")
    a_to_b = "{}to{}".format(a, b)
    a_to_b_formatted = "{}_s2fato{}_s2fa.nii.gz".format(a,b)
    pbtk_dir = join(sdir,"EDI","PBTKresults")
    a_to_b_file = join(pbtk_dir,a_to_b_formatted)
    bs = join(sdir,"bs.nii.gz")
    terminationmask = join(sdir,"terminationmask.nii.gz")
    exclusion_bsplusthalami = join(sdir,"exclusion_bsplusthalami.nii.gz")
    bedpostxResults = join(sdir,"bedpostx_b1000.bedpostX")
    merged = join(bedpostxResults,"merged")
    nodif_brain_mask = join(bedpostxResults,"nodif_brain_mask.nii.gz")
    tmp = join(sdir, "tmp", a_to_b)
    waypoints = join(tmp,"waypoint.txt")
    connectome_oneway = join(sdir, "connectome_oneway.dot")
    waytotal = join(tmp, "waytotal")
    if not exists(a_file) or not exists(b_file):
        raise Exception("Error: Both Freesurfer regions must exist: {} and {}".format(a_file, b_file))
    smart_remove(a_to_b_file)
    smart_remove(tmp)
    smart_mkdir(tmp)
    smart_mkdir(pbtk_dir)
    write(stdout, "Running subproc: {}".format(a_to_b))
    if container:
        odir = split(sdir)[0]
        write(waypoints, b_file.replace(odir, "/share"))
    else:
        write(waypoints, b_file)

    allvoxelscortsubcort = join(sdir,"allvoxelscortsubcort.nii.gz")
    exclusion = join(tmp,"exclusion.nii.gz")
    termination = join(tmp,"termination.nii.gz")
    run("fslmaths {} -sub {} {}".format(allvoxelscortsubcort, a_file, exclusion), params)
    run("fslmaths {} -sub {} {}".format(exclusion, b_file, exclusion), params)
    run("fslmaths {} -add {} {}".format(exclusion, bs, exclusion), params)
    run("fslmaths {} -add {} {}".format(terminationmask, b_file, termination), params)

    pbtx_args = (" -x {} ".format(a_file) +
        " --pd -l -c 0.2 -S 1000 --steplength=4.0 -P 100" +
        " --waypoints={} --avoid={} --stop={}".format(waypoints, exclusion, termination) +
        " --forcedir --opd" +
        " -s {}".format(merged) +
        " -m {}".format(nodif_brain_mask) +
        " --dir={}".format(tmp) +
        " --out={}".format(a_to_b_formatted)
        )
    if use_gpu:
        run("probtrackx2_gpu" + pbtx_args, params)
    else:
        run("probtrackx2" + pbtx_args, params)

    waytotal_count = 0
    with open(waytotal, 'r') as f:
        waytotal_count = f.read().strip()
        fdt_count = run("fslmeants -i {} -m {} | head -n 1".format(join(tmp, a_to_b_formatted), b_file), params) # based on getconnectome script
        if not is_float(waytotal_count):
            raise Exception("Error: Failed to read waytotal_count value {}".format(waytotal_count))
        if not is_float(fdt_count):
            raise Exception("Error: Failed to read fdt_count value {}".format(fdt_count))
        write(connectome_oneway, "{} {} {} {}".format(a, b, waytotal_count, fdt_count))
    copyfile(join(tmp, a_to_b_formatted), a_to_b_file) # keep edi output
    if not a == "lh.paracentral": # discard all temp files except these for debugging
        smart_remove(tmp)
    record_apptime(params, start_time, 1, a, b)

@python_app(executors=['s3'], cache=True)
def s3_3_combine(params, inputs=[]):
    import time
    from subscripts.utilities import record_apptime,record_finish,update_permissions,is_float,write
    from os.path import join,exists
    sdir = params['sdir']
    start_time = time.time()
    connectome_oneway = join(sdir, "connectome_oneway.dot")
    connectome_twoway = join(sdir, "connectome_twoway.dot")
    smart_remove(join(sdir, "connectome_twoway.dot"))
    processed_edges = {}
    if not exists(connectome_oneway):
        raise Exception("Error: Failed to generate {}".format(connectome_oneway))
    with open(connectome_oneway,'r') as f:
        for line in f.readlines():
            if not line:
                continue
            chunks = [x.strip() for x in line.strip().split(' ') if x]
            if len(chunks) >= 3:
                a_to_b = (chunks[0], chunks[1])
                b_to_a = (chunks[1], chunks[0])
                waytotal_count = float(chunks[2])
                fdt_count = float(chunks[3]) if len(chunks) >= 4 else 0
                if b_to_a in processed_edges:
                    processed_edges[b_to_a][0] += waytotal_count
                    processed_edges[b_to_a][1] += fdt_count
                else:
                    processed_edges[a_to_b] = [waytotal_count, fdt_count]
    for a_to_b in processed_edges:
        write(connectome_twoway, "{} {} {} {}".format(a_to_b[0], a_to_b[1], processed_edges[a_to_b][0], processed_edges[a_to_b][1]))
    update_permissions(params)
    record_apptime(params, start_time, 2)
    record_finish(params)

def run_s3(params, inputs):
    sdir = params['sdir']
    stdout = params['stdout']
    edge_list = params['edge_list']
    s3_1_future = s3_1_start(params, inputs=inputs)
    s3_2_futures = []
    processed_edges = []
    smart_remove(join(sdir, "connectome_oneway.dot"))
    smart_remove(join(sdir, "waytotal_oneway.dot"))
    smart_remove(join(sdir, "tmp"))
    with open(edge_list) as f:
        for edge in f.readlines():
            if edge.isspace():
                continue
            a, b = edge.replace("_s2fa", "").strip().split(',', 1)
            a_to_b = "{}to{}".format(a, b)
            b_to_a = "{}to{}".format(b, a)
            if a_to_b not in processed_edges and b_to_a not in processed_edges:
                s3_2_futures.append(s3_2_probtrackx(params, a, b, inputs=[s3_1_future]))
                s3_2_futures.append(s3_2_probtrackx(params, b, a, inputs=[s3_1_future]))
                processed_edges.append(a_to_b)
                processed_edges.append(b_to_a)
    return s3_3_combine(params, inputs=s3_2_futures)
