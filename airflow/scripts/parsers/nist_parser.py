# -*- coding: utf-8 -*-,
import pandas, json,os, sys, shutil, glob, csv
from pathlib import Path
from typing import List, Dict

# --- Added: streamlined Flow Cytometry parser for WG1/2/3 use in Airflow ---

def _coerce_str(v) -> str:
    if v is None:
        return ""
    try:
        return str(v)
    except Exception:
        return ""

def parse_flow_wg_from_dir(input_dir: str, collection: str = "fcs_interlab_study") -> List[Dict]:
    """Parse WG1/2/3 Excel files in input_dir (data/raw) and return file rows.

    - Accepts files matching WG*part*Table.xlsx and wg*-ver*-all.xlsx
    - Returns a list of dicts containing FileName, DatasetId, CollectionId, file_id,
      plus all original row fields (as strings), with NaNs coerced to "".
    """
    in_path = Path(input_dir)
    if not in_path.exists():
        raise RuntimeError(f"Input directory does not exist: {input_dir}")

    pats = ["WG*part*Table.xlsx", "wg*-ver*-all.xlsx"]
    excel_files: List[Path] = []
    for p in pats:
        excel_files.extend(in_path.glob(p))

    if not excel_files:
        raise RuntimeError(f"No WG1/2/3 Excel files found in {input_dir}")

    hierarchy_fields = [
        "WorkingGroup",
        "InstrumentCode",
        "SiteCode",
        "ProtocolID",
        "ExperimentType",
        "SampleName",
        "PrincipleContactID",
        "DataProcessingLevel",
        "StudyID",
        "MaterialCode",
        "ExperimentID",
        "ReplicateNumber",
        "DataFormat",
    ]

    out_rows: List[Dict] = []
    for excel in excel_files:
        try:
            xls = pandas.ExcelFile(excel)
            sheet = "Sheet1" if "Sheet1" in xls.sheet_names else xls.sheet_names[0]
        except Exception as e:
            raise RuntimeError(f"Failed to read Excel file {excel}: {e}")

        df = pandas.read_excel(excel, sheet_name=sheet, dtype=str).fillna("")
        for _, r in df.iterrows():
            row = {k: _coerce_str(v) for k, v in r.to_dict().items()}

            filename = row.get("New FCSC ILS Filename") or row.get("FCSC ILS Filename") or row.get("FileName")
            filename = _coerce_str(filename).strip()
            if not filename:
                continue

            # optional tweak from legacy: append -001 to WorkingGroup if present
            if row.get("WorkingGroup"):
                row["WorkingGroup"] = f"{row['WorkingGroup']}-001"

            segments: List[str] = []
            for f in hierarchy_fields:
                if row.get(f, "").strip():
                    segments.append(row[f].strip())

            dataset_id = "/".join([collection] + segments) if segments else collection
            file_id = f"{dataset_id}/{filename}"

            record = dict(row)
            record["DatasetId"] = dataset_id
            record["CollectionId"] = collection
            # Ensure CollectionName is present for downstream Solr requirements
            if not record.get("CollectionName"):
                record["CollectionName"] = collection
            # Ensure DatasetName is present; use the immediate parent folder (last segment of DatasetId)
            if not record.get("DatasetName"):
                record["DatasetName"] = dataset_id.split("/")[-1] if dataset_id else ""
            # Ensure DatasetVersion is present for Solr; default to '1'
            if not record.get("DatasetVersion"):
                record["DatasetVersion"] = "1"
            record["FileName"] = filename
            record["file_id"] = file_id

            out_rows.append(record)

    return out_rows

def write_cfgs(files: List[Dict], output_dir: str) -> None:
    """Write dataset-level cfgs down the hierarchy and a file-level cfg per file.

    This does not copy/move actual data. Output is under output_dir/Collection/...
    """
    root = Path(output_dir)
    for rec in files:
        dataset_id = _coerce_str(rec.get("DatasetId", ""))
        filename = _coerce_str(rec.get("FileName", "")).strip()
        if not dataset_id or not filename:
            # Skip malformed entries
            continue

        parts = dataset_id.split("/") + [filename]

        # Dataset fields exclude the file name
        ds_fields = dict(rec)
        ds_fields.pop("FileName", None)
        ds_fields.pop("New FCSC ILS Filename", None)

        # Build the [File] cfg once
        file_cfg = "[File]\n"
        # Ensure an explicit id for file docs; many publish paths expect it
        file_cfg += f"id={_coerce_str(rec.get('file_id', ''))}\n"
        for k in ds_fields:
            if k == "file_id":
                continue
            v = _coerce_str(rec.get(k, ""))
            if v != "":
                file_cfg += f"{k}={v}\n"

        # Write dataset cfgs for each path component
        for i in range(0, len(parts) - 1):
            ds_dir = root.joinpath(*parts[0 : i + 1])
            ds_dir.mkdir(parents=True, exist_ok=True)

            # Build per-level dataset fields and ensure DatasetName reflects this level
            local_ds_fields = dict(ds_fields)
            local_ds_fields["id"] = str(ds_dir)
            local_ds_fields["DatasetName"] = parts[i]

            ds_cfg = "[Dataset]\n"
            for k in local_ds_fields:
                v = _coerce_str(local_ds_fields.get(k, ""))
                if v != "":
                    ds_cfg += f"{k}={v}\n"

            cfg_path = ds_dir / f"{parts[i]}.cfg"
            with cfg_path.open("w", encoding="utf-8") as fh:
                fh.write(ds_cfg)

        # Finally, write the file-level cfg in the deepest dataset directory
        deepest_dir = root.joinpath(*parts[:-1])
        deepest_dir.mkdir(parents=True, exist_ok=True)
        file_cfg_path = deepest_dir / f"{filename}.cfg"
        with file_cfg_path.open("w", encoding="utf-8") as fh:
            fh.write(file_cfg)

# --- End added section ---


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Parse Flow Cytometry WG1/2/3 sheets to LabCAS cfgs")
    parser.add_argument("--input-dir", default="/data/raw", help="Directory containing WG*.xlsx files (mounted at /data/raw)")
    parser.add_argument("--output-dir", default="/metadata", help="Directory to write cfgs (mounted at /metadata)")
    parser.add_argument("--collection", default="fcs_interlab_study", help="Collection name for dataset hierarchy")
    args = parser.parse_args()

    files = parse_flow_wg_from_dir(args.input_dir, collection=args.collection)
    # Ensure output dir exists
    Path(args.output_dir).mkdir(parents=True, exist_ok=True)
    write_cfgs(files, args.output_dir)
    print(f"Wrote cfgs for {len(files)} files under {args.output_dir}")

root_metadata_path = "metadata"

replaced_chars = ["'","#"," ","/",",",":"]

def replaceMultiple(s, unwanted, input_char):
    # Iterate over the strings to be replaced
    for elem in unwanted:
        # Replace the string, does not do anything if `elem` not in `s`
        s = s.replace(elem, input_char)
    return s


def flow_cyt_parser():
    """Deprecated wrapper retained for compatibility.

    Parses WG1/2/3 spreadsheets from /data/raw and returns file records.
    Use the CLI or parse_flow_wg_from_dir directly instead.
    """
    return parse_flow_wg_from_dir("/data/raw", collection="fcs_interlab_study")
def cell_provenance():
    #Flow cytometry - choose one of the below to parse, not both
    #file_list = ["/Users/Programmer/Documents/Projects/Labcas/labcas-data/NIST/Cell Lines/Cellline provenance metadata and data20230417031610/VCN provenance table JPL 02232023(john.elliott@nist.gov).xlsx"]
    #file_list = ["/Users/Programmer/Documents/Projects/Labcas/labcas-data/NIST/Cell Lines/VCN provenance table JPL instances 060152023.xlsx"]
    file_list = ["/Users/Programmer/Documents/Projects/Labcas/labcas-data/NIST/Cell Lines/cell_provenance_example_3.xlsx"]

    collections = ["fcs_interlab_study","Genomics_Editing_Consortium","cell_line_provenance"]
    collection_id = 2

    count = 0

    dataasets = {}
    files = []

    for file in file_list:
        #sheet = "JPL Sheet"

        #sheet = "Sheet1"
        sheet = "cell_provenance_example_3"
        excel_data_df = pandas.read_excel(file, sheet_name=sheet)
        result = excel_data_df.to_json(orient="records")
        data = json.loads(result)
        #data = []
        #with open(file, 'r') as csv_file:
        #    csv_reader = csv.DictReader(csv_file)
        #    data = list(csv_reader)


        # print whole sheet data
        #print data



        for l in data:
            dataset = {}
            print (l)
            if "StandardizedFileName" in l and l["StandardizedFileName"]:
                count += 1

                #Datasets
                dataset_id = collections[collection_id]
                #for d in [l["WorkingGroup"],l["InstrumentCode"],l["SiteCode"],l["ProtocolID"]]:
                #for d in [l["CellCode"],l["ExpansionType"],l["EventType"],l["EventDate"],l["ThisPassageNumber"],l["InstrumentName"],l["FileFormat"]]:
                for d in [l["MammalianCellHandle"],l["ExpansionType"],l["EventType"],l["EventDate"],l["PassageNumber"],l["InstrumentHandle"],l["FileFormat"]]:
                    if str(d).strip() == "":
                          print("Error, there's a dataset w/o any values")
                          print (d)
                          #sys.exit()
                    dataset_id += "/"+str(d).encode('ascii', errors='ignore').decode().replace("/","-")
                    modified_l = l.copy()

                    modified_l["id"] = dataset_id
                    modified_l["DatasetName"] = d
                    modified_l["CollectionId"] = collections[collection_id]

                    #String replace invalid characters
                    for k, v in modified_l.iteritems():
                        if(isinstance(v, int)):
                            v = str(v)
                        elif(isinstance(v, float)):
                            v = float(v)
                        elif (v is not None):
                            modified_l[k] = v.encode('utf-8')

                    dataasets[dataset_id] = modified_l

                #Files
                file_id = "/".join([dataset_id,str(l["StandardizedFileName"])])

                print ("file_id")
                print (file_id)

                modified_l = l.copy()

                modified_l["id"] = file_id
                modified_l["file_id"] = file_id
                if l["StandardizedFileName"]  or l["StandardizedFileName"].strip()  != "":
                    modified_l["FileName"] = l["StandardizedFileName"]
                else:
                    modified_l["FileName"] = "None"

                modified_l["DatasetId"] = dataset_id
                modified_l["CollectionId"] = collections[collection_id]

                #String replace invalid characters
                for k, v in modified_l.iteritems():
                    if(isinstance(v, int)):
                        v = str(v)
                    elif(isinstance(v, float)):
                        v = float(v)
                    #modified_l[k] = replaceMultiple(v.encode('utf-8'), replaced_chars, "_")
                    elif (v is not None):
                        modified_l[k] = v.encode('ascii', errors='ignore').decode()
                files.append(modified_l)

        with open(collections[collection_id]+"-datasets.txt", "wb") as d_inp:
            #print list(dataasets.values())
            d_inp.write(json.dumps(list(dataasets.values())))

        with open(collections[collection_id]+"-files.txt", "wb") as f_inp:
            f_inp.write(json.dumps(files))


    return files

def generate_metadata(files, root_metadata_path, collection):


    for l in files:
        #file_id_split = l["id"].split("/")
        file_id_split = l["DatasetId"].split("/")+[l['FileName']]
        filename = l['FileName']
        modified_l = l
        if 'FileName' in modified_l:
            del modified_l['FileName']
        if 'New FCSC ILS Filename' in modified_l:
            del modified_l['New FCSC ILS Filename']

        cfg_file_detail = "[File]\n"
        #for i in range(0,len(file_id_split)-1):
        for i in range(0,len(file_id_split)-1):
            #make dataset dir
            cfg_file = "[Dataset]\n"

            dir_path  = root_metadata_path+"/"+"/".join(file_id_split[0:i+1])
            #print dir_path
            if (not os.path.exists(dir_path)):
                os.mkdir(dir_path)

            modified_l['id'] = dir_path

            for k in modified_l:
                if l[k] is not None:
                    cfg_file += k+"="+str(l[k])+"\n"

            if cfg_file_detail == "[File]\n":
                for k in modified_l:
                    if k == "file_id":
                        continue
                    if k == "id":
                        cfg_file_detail += k+"="+l["file_id"]+"\n" #use string replaced file_id
                    else:
                        if l[k] is not None:
                            cfg_file_detail += k+"="+str(l[k])+"\n"

            print ("cfg_file")
            print (cfg_file)
            with open(dir_path+"/"+file_id_split[i]+".cfg", "w") as d_inp:
                d_inp.write(cfg_file.encode('ascii', errors='ignore').decode())


        file_path  = root_metadata_path+"/"+"/".join(file_id_split)

        #adhoc custom code: for FCS files, move file to new location
        existing_file_dirpaths = ["",""]
        if collection == "fcs_interlab_study":
            #existing_file_dirpaths = ["/Users/Programmer/Documents/Projects/NIST/NIST_data/Flow Cytometry Collection/FW Reply to File request Flow cytometry data20220801103038/WG02 - RMs and Assay Procedures/WG2 SOP and Study Plan/Raw Data Files","/Users/Programmer/Documents/Projects/NIST/NIST_data/Flow Cytometry Collection/FW Reply to File request Flow cytometry data20220801103038/WG01 - ERF Calibration/SOP and Reporting Spreadsheet - WG1 ILS/Dry Run - Raw Data Files/ILS_FCSC_WG1-001_NISTGB-LW_DryRun"]
            existing_file_dirpaths = ["/Users/Programmer/Documents/Projects/Labcas/labcas-data/NIST/fcs/FCSC-ILS-01092023/WG1all","/Users/Programmer/Documents/Projects/Labcas/labcas-data/NIST/fcs/FCSC-ILS-01092023/WG2all"]
            #existing_file_dirpaths = ["/Users/Programmer/Documents/Projects/NIST/NIST_data/Flow Cytometry Collection/WG1part2","/Users/Programmer/Documents/Projects/NIST/NIST_data/Flow Cytometry Collection/WG2part2"]
            #existing_file_dirpaths = ["/Users/Programmer/Documents/Projects/NIST/NIST_data/Flow Cytometry Collection/FCSC ILS Upload 3/WG1part3","/Users/Programmer/Documents/Projects/NIST/NIST_data/Flow Cytometry Collection/FCSC ILS Upload 3/WG2part3"]
        elif collection == "Genomics_Editing_Consortium":
            existing_file_dirpaths = ["/Users/Programmer/Documents/Projects/Labcas/labcas-data/NIST/Cergentis/return_data/vcf", "/data/labcas-data/staging/","/data/labcas-data/staging/nanopore"]
        #elif collection == "cell_line_provenance":
        #    existing_file_dirpaths = ["/Users/Programmer/Documents/Projects/Labcas/labcas-data/NIST/Cergentis/return_data/vcf", "/Users/Programmer/Documents/Projects/Labcas/labcas-data/NIST/Cergentis/return_data/Return_Data","/Users/Programmer/Documents/Projects/Labcas/labcas-data/NIST/NONE"]

        if os.path.isfile(existing_file_dirpaths[0]+"/"+filename):
            shutil.copy(existing_file_dirpaths[0]+"/"+filename, file_path)
            print("copied 1!")
        elif os.path.isfile(existing_file_dirpaths[1]+"/"+filename):
            shutil.copy(existing_file_dirpaths[1]+"/"+filename, file_path)
            print("copied 2!")
        elif len(glob.glob(existing_file_dirpaths[2]+"/*/"+filename)) > 0:
            shutil.copy(glob.glob(existing_file_dirpaths[2]+"/*/"+filename)[0], file_path)
            print("copied 3!")
            print ("OK")
        elif len(glob.glob(existing_file_dirpaths[2]+"/*/*/"+filename)) > 0:
            shutil.copy(glob.glob(existing_file_dirpaths[2]+"/*/*/"+filename)[0], file_path)
            print("copied 4!")
            print ("OK")
        elif len(glob.glob(existing_file_dirpaths[2]+"/*/*/*/"+filename)) > 0:
            shutil.copy(glob.glob(existing_file_dirpaths[2]+"/*/*/*/"+filename)[0], file_path)
            print("copied 5!")
            print ("OK")
        else:
            with open(file_path, "w") as f_inp:
                f_inp.write("")
        print(file_path)

        with open(file_path+".cfg", "w") as f_inp:
            f_inp.write(cfg_file_detail.encode('ascii', errors='ignore').decode())



def genome_parser_bion():

    bion_files = [["A_-_Molecule_Filter_800Gbp_RawMolecules.filtered.bnx.gz","raw"],["A_-_Molecule_Merge_RawMolecules.bnx.gz","raw"],["B_-_Molecule_Filter_800Gbp_RawMolecules.filtered.bnx.gz","raw"],["B_-_Molecule_Merge_RawMolecules.bnx.gz","raw"],["C_-_Molecule_Filter_800Gbp_RawMolecules.filtered.bnx.gz","raw"],["C_-_Molecule_Merge_RawMolecules.bnx.gz","raw"],["D_-_Molecule_Filter_800Gbp_D_merged_minlen150_5Tbp.filtered.bnx.gz","raw"],["D_merged_minlen150_5Tbp_D_merged_minlen150_5Tbp.bnx.gz","raw"],["E_-_Molecule_Filter_800Gbp_E_merged_minlen150_5Tbp.filtered.bnx.gz","raw"],["E_merged_minlen150_5Tbp_E_merged_minlen150_5Tbp.bnx.gz","raw"],["A_-_De_novo_800Gbp_pipeline_results.zip","processed"],["A_-_Rare_Variant_Analysis_pipeline_results.zip","processed"],["B_-_De_novo_800Gbp_pipeline_results.zip","processed"],["B_-_Rare_Variant_Analysis_10_18_2021_17_11_48.zip","processed"],["B_-_Rare_Variant_Analysis_pipeline_results.zip","processed"],["C_-_De_novo_800Gbp_pipeline_results.zip","processed"],["C_-_Rare_Variant_Analysis_pipeline_results.zip","processed"],["D_-_De_novo_800Gbp_10_18_2021_17_13_50.zip","processed"],["D_-_De_novo_800Gbp_pipeline_results.zip","processed"],["D_-_Rare_Variant_Analysis_10_18_2021_17_12_5.zip","processed"],["D_-_Rare_Variant_Analysis_pipeline_results.zip","processed"],["E_-_De_novo_800Gbp_10_18_2021_17_14_6.zip","processed"],["E_-_De_novo_800Gbp_pipeline_results.zip","processed"],["E_-_Rare_Variant_Analysis_10_18_2021_17_12_20.zip","processed"],["E_-_Rare_Variant_Analysis_pipeline_results.zip","processed"]]

    #Genome editing - choose one of the below to parse, not both
    file = "/Users/Programmer/Documents/Projects/NIST/NIST_data/Genome Editing Collection/File_Extension_Bionano_v2.xlsx"
    sheet = "Experimental_Details"

    excel_data_df = pandas.read_excel(file, sheet_name=sheet)

    result = excel_data_df.to_json(orient="records")
    data = json.loads(result)
    # print whole sheet data

    collections = ["fcs_interlab_study","Genomics_Editing_Consortium","cell_line_provenance"]
    collection_id = 1

    count = 0

    dataasets = {}
    files = []

    for l in data:
        dataset = {}
        #if l["Sample_Name"]: TwinStrand
        if l["Sample"]: #Bionano
            count += 1


            #Datasets
            dataset_id = collections[collection_id]
            for d in [l["Institution"]]:
                #print l["Institution"]
                dataset_id += "/"+d
                modified_l = l.copy()

                modified_l["id"] = dataset_id
                modified_l["DatasetName"] = d
                modified_l["CollectionId"] = collections[collection_id]

                #String replace invalid characters
                for k, v in modified_l.iteritems():
                    if v is None:
                        v = ""

                    #modified_l[k] = replaceMultiple(str(v), replaced_chars, "_")
                    modified_l[k] = str(v)

                dataasets[dataset_id] = modified_l

            #processedlevel + associated file extension
            #for ext in [["raw","R1.fq.gz"],["raw","R2.fq.gz"],["processed","bai"],["processed","bam"]]: #TwinStrand
            for ext in bion_files:  #Bionano
                if not ext[0].startswith(l["Sample"]+"_"):
                    continue

                #Files
                file_id = "/".join([collections[collection_id],l["Institution"],l["Instrument"],l["Cells/DNA"],ext[0]])

                new_fileid_list = []
                print (file_id)

                dataset_id = "/".join([collections[collection_id],l["Institution"]])
                modified_l = l.copy()

                modified_l["id"] = file_id
                modified_l["file_id"] = file_id
                modified_l["ProcessingLevel"] = ext[1]
                modified_l["FileName"] = ext[0] #Bionano
                #modified_l["FileName"] = l["Sample_Name"]+"."+ext[1] #TwinStrand
                modified_l["FileType"] = [ext[1]]
                modified_l["DatasetId"] = dataset_id
                modified_l["CollectionId"] = collections[collection_id]

                #String replace invalid characters
                for k, v in modified_l.iteritems():
                    if v is None:
                        v = ""
                    modified_l[k] = str(v)

                files.append(modified_l)


    with open(collections[collection_id]+"-datasets.txt", "wb") as d_inp:
        #print list(dataasets.values())
        d_inp.write(json.dumps(list(dataasets.values())))

    with open(collections[collection_id]+"-files.txt", "wb") as f_inp:
        f_inp.write(json.dumps(files))

    return files
    
def microbe_parser():

    
    #Genome editing - choose one of the below to parse, not both
    files = ["File_SeqExtension_rhAmpSeq-NGS-ONT.xlsx"]
    sheet = "Compiled"

    excel_data_df = pandas.read_excel(file, sheet_name=sheet)
    excel_data_df.fillna('NA', inplace=True)
    result = excel_data_df.to_json(orient="records")
    data = json.loads(result)
    # print whole sheet data

    collections = ["fcs_interlab_study","Genomics_Editing_Consortium","cell_line_provenance", "Microbial"]
    collection_id = 3

    count = 0

    dataasets = {}
    files = []

    for l in data:
        dataset = {}
        #Datasets
        dataset_id = collections[collection_id]
        for d in [l["FileName"]]:
            #print l["Institution"]
            dataset_id += "/"+d
            modified_l = l.copy()

            modified_l["id"] = dataset_id
            modified_l["DatasetName"] = d
            modified_l["CollectionId"] = collections[collection_id]

            #String replace invalid characters
            for k, v in modified_l.items():
                if v is None:
                    v = ""

                #modified_l[k] = replaceMultiple(str(v), replaced_chars, "_")
                modified_l[k] = str(v)

            dataasets[dataset_id] = modified_l

        
        fcomp = [l["FileName"],""]


        if "*" in l["FileName"]:
            fcomp = l["FileName"].split("*")

        print (fcomp)
        
        cert_files = os.walk("/data/labcas-data/staging/nanopore/rhAmpSeq-NGS-ONT")
        for ext in cert_files:  #Bionano
            directory, midpath, filen = ext

            if len(filen) == 0:
                continue
            
            for filenn in filen:
                print ("filenn")
                print (filenn)
                if filenn.startswith(fcomp[0]) and filenn.endswith(fcomp[1]):
                
                    filen_split = filenn.split(".", 1)
                    #Files
                    print (l)
                    file_id = "/".join([collections[collection_id],l["InstitutionName"],l["Instrument"],l["SourceMaterial"],filenn])

                    print (file_id)

                    dataset_id = "/".join([collections[collection_id],l["InstitutionName"]])
                    modified_l = l.copy()

                    modified_l["id"] = file_id
                    modified_l["file_id"] = file_id
                    modified_l["FileName"] = filenn #Bionano
                    modified_l["FileType"] = [filen_split[1]]
                    modified_l["DatasetId"] = dataset_id
                    modified_l["CollectionId"] = collections[collection_id]

                    #String replace invalid characters
                    for k, v in modified_l.items():
                        if v is None:
                            v = ""
                        modified_l[k] = str(v)

                    files.append(modified_l)


    with open(collections[collection_id]+"-datasets.txt", "w") as d_inp:
        #print list(dataasets.values())
        d_inp.write(json.dumps(list(dataasets.values())))

    with open(collections[collection_id]+"-files.txt", "w") as f_inp:
        f_inp.write(json.dumps(files))

    return files
def genome_parser_mission():

    
    #Genome editing - choose one of the below to parse, not both
    file = "File_SeqExtension_rhAmpSeq-NGS-ONT.xlsx"
    sheet = "Sheet1"

    excel_data_df = pandas.read_excel(file, sheet_name=sheet)
    excel_data_df.fillna('NA', inplace=True)
    result = excel_data_df.to_json(orient="records")
    data = json.loads(result)
    # print whole sheet data

    collections = ["fcs_interlab_study","Genomics_Editing_Consortium","cell_line_provenance"]
    collection_id = 1

    count = 0

    dataasets = {}
    files = []

    for l in data:
        dataset = {}
        #Datasets
        dataset_id = collections[collection_id]
        for d in [l["InstitutionName"]]:
            #print l["Institution"]
            dataset_id += "/"+d
            modified_l = l.copy()

            modified_l["id"] = dataset_id
            modified_l["DatasetName"] = d
            modified_l["CollectionId"] = collections[collection_id]

            #String replace invalid characters
            for k, v in modified_l.items():
                if v is None:
                    v = ""

                #modified_l[k] = replaceMultiple(str(v), replaced_chars, "_")
                modified_l[k] = str(v)

            dataasets[dataset_id] = modified_l

        
        fcomp = [l["FileName"],""]


        if "*" in l["FileName"]:
            fcomp = l["FileName"].split("*")

        print (fcomp)
        
        cert_files = os.walk("/data/labcas-data/staging/nanopore/rhAmpSeq-NGS-ONT")
        for ext in cert_files:  #Bionano
            directory, midpath, filen = ext

            if len(filen) == 0:
                continue
            
            for filenn in filen:
                print ("filenn")
                print (filenn)
                if filenn.startswith(fcomp[0]) and filenn.endswith(fcomp[1]):
                
                    filen_split = filenn.split(".", 1)
                    #Files
                    print (l)
                    file_id = "/".join([collections[collection_id],l["InstitutionName"],l["Instrument"],l["SourceMaterial"],filenn])

                    print (file_id)

                    dataset_id = "/".join([collections[collection_id],l["InstitutionName"]])
                    modified_l = l.copy()

                    modified_l["id"] = file_id
                    modified_l["file_id"] = file_id
                    modified_l["FileName"] = filenn #Bionano
                    modified_l["FileType"] = [filen_split[1]]
                    modified_l["DatasetId"] = dataset_id
                    modified_l["CollectionId"] = collections[collection_id]

                    #String replace invalid characters
                    for k, v in modified_l.items():
                        if v is None:
                            v = ""
                        modified_l[k] = str(v)

                    files.append(modified_l)


    with open(collections[collection_id]+"-datasets.txt", "w") as d_inp:
        #print list(dataasets.values())
        d_inp.write(json.dumps(list(dataasets.values())))

    with open(collections[collection_id]+"-files.txt", "w") as f_inp:
        f_inp.write(json.dumps(files))

    return files
def genome_parser_cert():

    
    #Genome editing - choose one of the below to parse, not both
    file = "/Users/Programmer/Documents/Projects/NIST/NIST_data/Genome Editing Collection/File_SeqExtension_cergentis.xlsx"
    sheet = "Sheet1"

    excel_data_df = pandas.read_excel(file, sheet_name=sheet)

    result = excel_data_df.to_json(orient="records")
    data = json.loads(result)
    # print whole sheet data

    collections = ["fcs_interlab_study","Genomics_Editing_Consortium","cell_line_provenance"]
    collection_id = 1

    count = 0

    dataasets = {}
    files = []

    for l in data:
        dataset = {}
        #Datasets
        dataset_id = collections[collection_id]
        for d in [l["Institution"]]:
            #print l["Institution"]
            dataset_id += "/"+d
            modified_l = l.copy()

            modified_l["id"] = dataset_id
            modified_l["DatasetName"] = d
            modified_l["CollectionId"] = collections[collection_id]

            #String replace invalid characters
            for k, v in modified_l.iteritems():
                if v is None:
                    v = ""

                #modified_l[k] = replaceMultiple(str(v), replaced_chars, "_")
                modified_l[k] = str(v)

            dataasets[dataset_id] = modified_l

        
        fcomp = [l["FileName"],""]


        if "*" in l["FileName"]:
            fcomp = l["FileName"].split("*")

        print (fcomp)
        
        cert_files = os.walk("/Users/Programmer/Documents/Projects/Labcas/labcas-data/NIST/Cergentis/return_data/")
        for ext in cert_files:  #Bionano
            directory, midpath, filen = ext

            if len(filen) == 0:
                continue
            
            for filenn in filen:
                if filenn.startswith(fcomp[0]) and filenn.endswith(fcomp[1]):
                
                    filen_split = filenn.split(".", 1)
                    #Files
                    file_id = "/".join([collections[collection_id],l["Institution"],l["Instrument"],l["SourceMaterial"],filenn])

                    print (file_id)

                    dataset_id = "/".join([collections[collection_id],l["Institution"]])
                    modified_l = l.copy()

                    modified_l["id"] = file_id
                    modified_l["file_id"] = file_id
                    modified_l["FileName"] = filenn #Bionano
                    modified_l["FileType"] = [filen_split[1]]
                    modified_l["DatasetId"] = dataset_id
                    modified_l["CollectionId"] = collections[collection_id]

                    #String replace invalid characters
                    for k, v in modified_l.iteritems():
                        if v is None:
                            v = ""
                        modified_l[k] = str(v)

                    files.append(modified_l)


    with open(collections[collection_id]+"-datasets.txt", "wb") as d_inp:
        #print list(dataasets.values())
        d_inp.write(json.dumps(list(dataasets.values())))

    with open(collections[collection_id]+"-files.txt", "wb") as f_inp:
        f_inp.write(json.dumps(files))

    return files

def genome_parser_anon():

    
    #Genome editing - choose one of the below to parse, not both
    file = "/Users/Programmer/Documents/Projects/NIST/NIST_data/Genome Editing Collection/File_SeqExtension_anon.xlsx"
    sheet = "Sheet1"

    excel_data_df = pandas.read_excel(file, sheet_name=sheet)

    result = excel_data_df.to_json(orient="records")
    data = json.loads(result)
    # print whole sheet data

    collections = ["fcs_interlab_study","Genomics_Editing_Consortium","cell_line_provenance"]
    collection_id = 1

    count = 0

    dataasets = {}
    files = []
    folderRegMap = {
                "Amp-based-1": {
                        "NIST-A":"A",
                        "NIST-B":"B",
                        "NIST-C":"C",
                        "NIST-D":"D",
                        "NIST-E":"E"
                    },
                "Amp-based-2": {
                        "_A":"A",
                        "_B":"B",
                        "_C":"C",
                        "_D":"D",
                        "_E":"E"
                    },
                "Amp-based-3": {
                        "SNA114912-384W1771-P2_S375":"A",
"SNA114912-001_AMP21029":"A",
"SNA114912-384W1771-P8_S459":"A",
"SNA114912-384W1771-N6_S435":"A",
"SNA114912-384W1771-N12_S443":"A",
"SNA114912-384W1771-J6_S355":"A",
"SNA114912-384W1771-F12_S461":"A",
"SNA114912-384W1771-H12_S463":"A",
"SNA114912-384W1771-H4_S232":"A",
"SNA114912-384W1771-J4_S228":"A",
"SNA114912-384W1771-B10_S250":"A",
"SNA114912-384W1771-H8_S254":"A",
"SNA114912-384W1771-L10_S395":"A",
"SNA114912-384W1771-N4_S386":"A",
"SNA114912-384W1771-D10_S251":"A",
"SNA114912-384W1771-B14_S266":"A",
"SNA114912-384W1771-B12_S378":"A",
"SNA114912-001_AMP21019":"A",
"SNA114912-384W1771-H6_S379":"A",
"SNA114912-384W1771-J12_S263":"A",
"SNA114912-384W1771-D14_S421":"A",
"SNA114912-384W1771-B2_S238":"A",
"SNA114912-384W1771-L4_S406":"A",
"SNA114912-384W1771-B6_S410":"A",
"SNA114912-384W1771-D12_S323":"A",
"SNA114912-384W1771-L12_S214":"A",
"SNA114912-384W1771-H10_S211":"A",
"SNA114912-384W1771-N2_S217":"A",
"SNA114912-384W1771-P6_S458":"A",
"SNA114912-384W1771-B8_S313":"A",
"SNA114912-384W1771-F4_S384":"A",
"SNA114912-384W1771-L6_S221":"A",
"SNA114912-384W1771-D8_S401":"A",
"SNA114912-384W1771-P12_S258":"A",
"SNA114912-384W1771-F6_S259":"A",
"SNA114912-384W1771-J10_S310":"A",
"SNA114912-384W1771-F10_S312":"A",
"SNA114912-384W1771-F8_S305":"A",
"SNA114912-384W1771-N10_S314":"A",
"SNA114912-384W1771-P10_S244":"A",
"SNA114912-384W1771-L8_S347":"A",
"SNA114912-384W1771-B4_S301":"A",
"SNA114912-384W1771-N8_S240":"A",
"SNA114912-384W1771-J8_S247":"A",
"SNA114912-384W1771-P4_S264":"A",
"SNA114912-384W1771-L2_S404":"A",
"SNA114912-384W1771-D6_S296":"A",
"SNA114912-384W1773-C21_S187":"A",
"SNA114913-384W1826-O11_S154":"B",
"SNA114913-384W1826-A7_S187":"B",
"SNA114913-384W1826-K1_S156":"B",
"SNA114913-384W1826-C13_S135":"B",
"SNA114913-384W1826-G3_S194":"B",
"SNA114913-384W1826-E9_S165":"B",
"SNA114913-384W1826-A9_S101":"B",
"SNA114913-384W1826-M9_S122":"B",
"SNA114913-384W1826-K5_S22":"B",
"SNA114913-384W1826-A1_S166":"B",
"SNA114913-384W1826-K3_S172":"B",
"SNA114913-384W1826-E7_S70":"B",
"SNA114913-384W1826-M3_S176":"B",
"SNA114913-384W1826-A13_S63":"B",
"SNA114913-001_AMP21029":"B",
"SNA114913-384W1826-I7_S132":"B",
"SNA114913-384W1826-O3_S64":"B",
"SNA114913-384W1826-O7_S186":"B",
"SNA114913-384W1826-O1_S133":"B",
"SNA114913-384W1826-O5_S198":"B",
"SNA114913-384W1826-E11_S179":"B",
"SNA114913-384W1826-E5_S65":"B",
"SNA114913-384W1826-M5_S206":"B",
"SNA114913-384W1826-K11_S40":"B",
"SNA114913-384W1826-G9_S75":"B",
"SNA114913-384W1826-C7_S152":"B",
"SNA114913-384W1826-C5_S82":"B",
"SNA114913-384W1826-G11_S9":"B",
"SNA114913-384W1826-I11_S10":"B",
"SNA114913-384W1826-M7_S2":"B",
"SNA114913-384W1826-A11_S125":"B",
"SNA114913-384W1826-I3_S106":"B",
"SNA114913-384W1826-C11_S32":"B",
"SNA114913-384W1826-E3_S128":"B",
"SNA114913-384W1826-O9_S11":"B",
"SNA114913-384W1826-K7_S113":"B",
"SNA114913-384W1826-K9_S44":"B",
"SNA114913-384W1826-G7_S30":"B",
"SNA114913-384W1826-I9_S47":"B",
"SNA114913-384W1826-A3_S145":"B",
"SNA114913-384W1826-I5_S27":"B",
"SNA114913-384W1826-G5_S146":"B",
"SNA114913-384W1826-C3_S14":"B",
"SNA114913-384W1826-M11_S142":"B",
"SNA114913-384W1826-M1_S93":"B",
"SNA114913-384W1826-A5_S86":"B",
"SNA114913-384W1826-C9_S96":"B",
"SNA114914-384W1826-I12_S71":"C",
"SNA114914-384W1826-G10_S173":"C",
"SNA114914-384W1826-K12_S164":"C",
"SNA114914-384W1826-O6_S35":"C",
"SNA114914-384W1826-O12_S20":"C",
"SNA114914-384W1826-K4_S170":"C",
"SNA114914-001_AMP21029":"C",
"SNA114914-384W1826-K6_S72":"C",
"SNA114914-384W1826-A6_S36":"C",
"SNA114914-384W1826-M6_S160":"C",
"SNA114914-384W1826-I6_S188":"C",
"SNA114914-384W1826-C6_S121":"C",
"SNA114914-384W1826-A2_S195":"C",
"SNA114914-384W1826-C14_S184":"C",
"SNA114914-001_AMP20978":"C",
"SNA114912-384W1773-C21_S187":"C",
"SNA114914-384W1826-O8_S175":"C",
"SNA114914-384W1826-E10_S136":"C",
"SNA114914-384W1826-G4_S196":"C",
"SNA114914-384W1826-A8_S149":"C",
"SNA114914-384W1826-A12_S190":"C",
"SNA114914-384W1826-C10_S197":"C",
"SNA114914-384W1826-C8_S39":"C",
"SNA114914-384W1826-A4_S97":"C",
"SNA114914-384W1826-M2_S15":"C",
"SNA114914-384W1826-E6_S5":"C",
"SNA114914-384W1826-K2_S16":"C",
"SNA114914-384W1826-C12_S98":"C",
"SNA114914-384W1826-A14_S115":"C",
"SNA114914-384W1826-M8_S66":"C",
"SNA114914-384W1826-E12_S17":"C",
"SNA114914-384W1826-K8_S181":"C",
"SNA114914-384W1826-O4_S153":"C",
"SNA114914-384W1826-O2_S108":"C",
"SNA114914-384W1826-G6_S100":"C",
"SNA114914-384W1826-I4_S77":"C",
"SNA114914-384W1826-C4_S19":"C",
"SNA114914-384W1826-G12_S69":"C",
"SNA114914-384W1826-K10_S107":"C",
"SNA114914-384W1826-M4_S51":"C",
"SNA114914-384W1826-A10_S140":"C",
"SNA114914-384W1826-E8_S114":"C",
"SNA114914-384W1826-O10_S130":"C",
"SNA114914-384W1826-M12_S94":"C",
"SNA114914-384W1826-G8_S24":"C",
"SNA114914-384W1826-I8_S89":"C",
"SNA114914-384W1826-E4_S105":"C",
"SNA114915-001_AMP21029":"D",
"SNA114915-384W1826-J7_S199":"D",
"SNA114915-384W1826-P1_S183":"D",
"SNA114915-384W1826-P9_S178":"D",
"SNA114915-384W1826-N3_S202":"D",
"SNA114915-384W1826-N7_S168":"D",
"SNA114915-384W1826-H5_S189":"D",
"SNA114915-384W1826-L9_S204":"D",
"SNA114915-384W1826-J3_S185":"D",
"SNA114915-384W1826-F5_S102":"D",
"SNA114915-384W1826-L5_S162":"D",
"SNA114915-384W1826-J11_S137":"D",
"SNA114915-384W1826-B13_S167":"D",
"SNA114915-384W1826-B9_S150":"D",
"SNA114915-384W1826-D13_S80":"D",
"SNA114915-384W1826-B5_S124":"D",
"SNA114915-384W1826-D5_S7":"D",
"SNA114915-384W1826-N9_S81":"D",
"SNA114915-384W1826-F3_S117":"D",
"SNA114915-384W1826-D11_S180":"D",
"SNA114915-384W1826-N11_S58":"D",
"SNA114915-384W1826-P7_S54":"D",
"SNA114915-384W1826-L3_S1":"D",
"SNA114915-001_AMP21019":"D",
"SNA114915-384W1826-J5_S76":"D",
"SNA114915-384W1826-D9_S60":"D",
"SNA114915-001_AMP21013":"D",
"SNA114915-384W1826-P11_S127":"D",
"SNA114915-384W1826-P5_S55":"D",
"SNA114915-384W1826-N1_S68":"D",
"SNA114915-384W1826-J9_S112":"D",
"SNA114915-384W1826-L11_S109":"D",
"SNA114915-384W1826-N5_S43":"D",
"SNA114915-384W1826-B7_S56":"D",
"SNA114915-384W1826-L1_S3":"D",
"SNA114915-384W1826-D7_S126":"D",
"SNA114915-384W1826-L7_S78":"D",
"SNA114915-384W1826-H3_S33":"D",
"SNA114915-384W1826-F11_S144":"D",
"SNA114915-384W1826-P3_S110":"D",
"SNA114915-384W1826-F9_S129":"D",
"SNA114915-384W1826-B11_S103":"D",
"SNA114915-384W1826-H11_S52":"D",
"SNA114915-384W1826-F7_S13":"D",
"SNA114915-384W1826-H9_S28":"D",
"SNA114915-384W1826-H7_S104":"D",
"SNA114915-384W1826-B1_S87":"D",
"SNA114916-384W1826-J6_S120":"E",
"SNA114916-001_AMP21029":"E",
"SNA114916-384W1826-P8_S201":"E",
"SNA114916-384W1826-L4_S159":"E",
"SNA114916-384W1826-D8_S155":"E",
"SNA114916-384W1826-N6_S182":"E",
"SNA114916-384W1826-N12_S191":"E",
"SNA114916-384W1826-P2_S134":"E",
"SNA114916-384W1826-P6_S200":"E",
"SNA114916-384W1826-H4_S21":"E",
"SNA114916-384W1826-D14_S171":"E",
"SNA114916-384W1826-D6_S74":"E",
"SNA114916-384W1826-B10_S37":"E",
"SNA114916-384W1826-D10_S38":"E",
"SNA114916-384W1826-L2_S158":"E",
"SNA114916-384W1826-F12_S205":"E",
"SNA114916-384W1826-H6_S139":"E",
"SNA114916-384W1826-B6_S163":"E",
"SNA114916-384W1826-B12_S138":"E",
"SNA114916-384W1826-L10_S151":"E",
"SNA114916-384W1826-B14_S53":"E",
"SNA114916-384W1826-L12_S6":"E",
"SNA114916-384W1826-N2_S8":"E",
"SNA114916-384W1826-H8_S41":"E",
"SNA114916-384W1826-D12_S99":"E",
"SNA114916-384W1826-H12_S207":"E",
"SNA114916-384W1826-L8_S116":"E",
"SNA114916-384W1826-J4_S18":"E",
"SNA114916-384W1826-J12_S49":"E",
"SNA114916-384W1826-P12_S45":"E",
"SNA114916-384W1826-N4_S143":"E",
"SNA114916-384W1826-P4_S50":"E",
"SNA114916-384W1826-F6_S46":"E",
"SNA114916-001_AMP21019":"E",
"SNA114916-384W1826-B2_S26":"E",
"SNA114916-384W1826-L6_S12":"E",
"SNA114916-384W1826-H10_S4":"E",
"SNA114916-384W1826-B4_S79":"E",
"SNA114916-384W1826-J8_S34":"E",
"SNA114916-384W1826-B8_S91":"E",
"SNA114916-384W1826-J10_S88":"E",
"SNA114916-384W1826-F8_S83":"E",
"SNA114916-384W1826-P10_S31":"E",
"SNA114916-384W1826-F4_S141":"E",
"SNA114916-384W1826-N10_S92":"E",
"SNA114916-384W1826-N8_S29":"E",
"SNA114916-384W1826-F10_S90":"E",
"SNA114916-384W1773-G3_S253":"E",
"SNA114912-384W1771-B10_S250_L001":"A",
"SNA114912-384W1771-B12_S378_L001":"A",
"SNA114912-384W1771-B14_S266_L001":"A",
"SNA114912-384W1771-B6_S410_L001":"A",
"SNA114912-384W1771-B8_S313_L001":"A",
"SNA114912-384W1771-D10_S251_L001":"A",
"SNA114912-384W1771-D12_S323_L001":"A",
"SNA114912-384W1771-D14_S421_L001":"A",
"SNA114912-384W1771-D6_S296_L001":"A",
"SNA114912-384W1771-D8_S401_L001":"A",
"SNA114912-384W1771-F10_S312_L001":"A",
"SNA114912-384W1771-F12_S461_L001":"A",
"SNA114912-384W1771-F6_S259_L001":"A",
"SNA114912-384W1771-F8_S305_L001":"A",
"SNA114912-384W1771-H10_S211_L001":"A",
"SNA114912-384W1771-H12_S463_L001":"A",
"SNA114912-384W1771-H4_S232_L001":"A",
"SNA114912-384W1771-H6_S379_L001":"A",
"SNA114912-384W1771-H8_S254_L001":"A",
"SNA114912-384W1771-J10_S310_L001":"A",
"SNA114912-384W1771-J12_S263_L001":"A",
"SNA114912-384W1771-J4_S228_L001":"A",
"SNA114912-384W1771-J6_S355_L001":"A",
"SNA114912-384W1771-J8_S247_L001":"A",
"SNA114912-384W1771-L10_S395_L001":"A",
"SNA114912-384W1771-L12_S214_L001":"A",
"SNA114912-384W1771-L4_S406_L001":"A",
"SNA114912-384W1771-L6_S221_L001":"A",
"SNA114912-384W1771-L8_S347_L001":"A",
"SNA114912-384W1771-N10_S314_L001":"A",
"SNA114912-384W1771-N12_S443_L001":"A",
"SNA114912-384W1771-N4_S386_L001":"A",
"SNA114912-384W1771-N6_S435_L001":"A",
"SNA114912-384W1771-N8_S240_L001":"A",
"SNA114912-384W1771-P10_S244_L001":"A",
"SNA114912-384W1771-P12_S258_L001":"A",
"SNA114912-384W1771-P4_S264_L001":"A",
"SNA114912-384W1771-P6_S458_L001":"A",
"SNA114912-384W1771-P8_S459_L001":"A",
"SNA114913-384W1826-A11_S125_L001":"B",
"SNA114913-384W1826-A13_S63_L001":"B",
"SNA114913-384W1826-A5_S86_L001":"B",
"SNA114913-384W1826-A7_S187_L001":"B",
"SNA114913-384W1826-A9_S101_L001":"B",
"SNA114913-384W1826-C11_S32_L001":"B",
"SNA114913-384W1826-C13_S135_L001":"B",
"SNA114913-384W1826-C5_S82_L001":"B",
"SNA114913-384W1826-C7_S152_L001":"B",
"SNA114913-384W1826-C9_S96_L001":"B",
"SNA114913-384W1826-E11_S179_L001":"B",
"SNA114913-384W1826-E5_S65_L001":"B",
"SNA114913-384W1826-E7_S70_L001":"B",
"SNA114913-384W1826-E9_S165_L001":"B",
"SNA114913-384W1826-G11_S9_L001":"B",
"SNA114913-384W1826-G3_S194_L001":"B",
"SNA114913-384W1826-G5_S146_L001":"B",
"SNA114913-384W1826-G7_S30_L001":"B",
"SNA114913-384W1826-G9_S75_L001":"B",
"SNA114913-384W1826-I11_S10_L001":"B",
"SNA114913-384W1826-I3_S106_L001":"B",
"SNA114913-384W1826-I5_S27_L001":"B",
"SNA114913-384W1826-I7_S132_L001":"B",
"SNA114913-384W1826-I9_S47_L001":"B",
"SNA114913-384W1826-K11_S40_L001":"B",
"SNA114913-384W1826-K3_S172_L001":"B",
"SNA114913-384W1826-K5_S22_L001":"B",
"SNA114913-384W1826-K7_S113_L001":"B",
"SNA114913-384W1826-K9_S44_L001":"B",
"SNA114913-384W1826-M11_S142_L001":"B",
"SNA114913-384W1826-M3_S176_L001":"B",
"SNA114913-384W1826-M5_S206_L001":"B",
"SNA114913-384W1826-M7_S2_L001":"B",
"SNA114913-384W1826-M9_S122_L001":"B",
"SNA114913-384W1826-O11_S154_L001":"B",
"SNA114913-384W1826-O3_S64_L001":"B",
"SNA114913-384W1826-O5_S198_L001":"B",
"SNA114913-384W1826-O7_S186_L001":"B",
"SNA114913-384W1826-O9_S11_L001":"B",
"SNA114914-384W1826-A10_S140_L001":"C",
"SNA114914-384W1826-A12_S190_L001":"C",
"SNA114914-384W1826-A14_S115_L001":"C",
"SNA114914-384W1826-A6_S36_L001":"C",
"SNA114914-384W1826-A8_S149_L001":"C",
"SNA114914-384W1826-C10_S197_L001":"C",
"SNA114914-384W1826-C12_S98_L001":"C",
"SNA114914-384W1826-C14_S184_L001":"C",
"SNA114914-384W1826-C6_S121_L001":"C",
"SNA114914-384W1826-C8_S39_L001":"C",
"SNA114914-384W1826-E10_S136_L001":"C",
"SNA114914-384W1826-E12_S17_L001":"C",
"SNA114914-384W1826-E6_S5_L001":"C",
"SNA114914-384W1826-E8_S114_L001":"C",
"SNA114914-384W1826-G10_S173_L001":"C",
"SNA114914-384W1826-G12_S69_L001":"C",
"SNA114914-384W1826-G4_S196_L001":"C",
"SNA114914-384W1826-G6_S100_L001":"C",
"SNA114914-384W1826-G8_S24_L001":"C",
"SNA114914-384W1826-I12_S71_L001":"C",
"SNA114914-384W1826-I4_S77_L001":"C",
"SNA114914-384W1826-I6_S188_L001":"C",
"SNA114914-384W1826-I8_S89_L001":"C",
"SNA114914-384W1826-K10_S107_L001":"C",
"SNA114914-384W1826-K12_S164_L001":"C",
"SNA114914-384W1826-K4_S170_L001":"C",
"SNA114914-384W1826-K6_S72_L001":"C",
"SNA114914-384W1826-K8_S181_L001":"C",
"SNA114914-384W1826-M10_S161_L001":"C",
"SNA114914-384W1826-M12_S94_L001":"C",
"SNA114914-384W1826-M4_S51_L001":"C",
"SNA114914-384W1826-M6_S160_L001":"C",
"SNA114914-384W1826-M8_S66_L001":"C",
"SNA114914-384W1826-O10_S130_L001":"C",
"SNA114914-384W1826-O12_S20_L001":"C",
"SNA114914-384W1826-O4_S153_L001":"C",
"SNA114914-384W1826-O6_S35_L001":"C",
"SNA114914-384W1826-O8_S175_L001":"C",
"SNA114915-384W1826-B11_S103_L001":"D",
"SNA114915-384W1826-B13_S167_L001":"D",
"SNA114915-384W1826-B5_S124_L001":"D",
"SNA114915-384W1826-B7_S56_L001":"D",
"SNA114915-384W1826-B9_S150_L001":"D",
"SNA114915-384W1826-D11_S180_L001":"D",
"SNA114915-384W1826-D13_S80_L001":"D",
"SNA114915-384W1826-D5_S7_L001":"D",
"SNA114915-384W1826-D7_S126_L001":"D",
"SNA114915-384W1826-D9_S60_L001":"D",
"SNA114915-384W1826-F11_S144_L001":"D",
"SNA114915-384W1826-F5_S102_L001":"D",
"SNA114915-384W1826-F7_S13_L001":"D",
"SNA114915-384W1826-F9_S129_L001":"D",
"SNA114915-384W1826-H11_S52_L001":"D",
"SNA114915-384W1826-H3_S33_L001":"D",
"SNA114915-384W1826-H5_S189_L001":"D",
"SNA114915-384W1826-H7_S104_L001":"D",
"SNA114915-384W1826-H9_S28_L001":"D",
"SNA114915-384W1826-J11_S137_L001":"D",
"SNA114915-384W1826-J3_S185_L001":"D",
"SNA114915-384W1826-J5_S76_L001":"D",
"SNA114915-384W1826-J7_S199_L001":"D",
"SNA114915-384W1826-J9_S112_L001":"D",
"SNA114915-384W1826-L11_S109_L001":"D",
"SNA114915-384W1826-L3_S1_L001":"D",
"SNA114915-384W1826-L5_S162_L001":"D",
"SNA114915-384W1826-L7_S78_L001":"D",
"SNA114915-384W1826-L9_S204_L001":"D",
"SNA114915-384W1826-N11_S58_L001":"D",
"SNA114915-384W1826-N3_S202_L001":"D",
"SNA114915-384W1826-N5_S43_L001":"D",
"SNA114915-384W1826-N7_S168_L001":"D",
"SNA114915-384W1826-N9_S81_L001":"D",
"SNA114915-384W1826-P11_S127_L001":"D",
"SNA114915-384W1826-P3_S110_L001":"D",
"SNA114915-384W1826-P5_S55_L001":"D",
"SNA114915-384W1826-P7_S54_L001":"D",
"SNA114915-384W1826-P9_S178_L001":"D",
"SNA114916-384W1826-B10_S37_L001":"E",
"SNA114916-384W1826-B12_S138_L001":"E",
"SNA114916-384W1826-B14_S53_L001":"E",
"SNA114916-384W1826-B6_S163_L001":"E",
"SNA114916-384W1826-B8_S91_L001":"E",
"SNA114916-384W1826-D10_S38_L001":"E",
"SNA114916-384W1826-D12_S99_L001":"E",
"SNA114916-384W1826-D14_S171_L001":"E",
"SNA114916-384W1826-D6_S74_L001":"E",
"SNA114916-384W1826-D8_S155_L001":"E",
"SNA114916-384W1826-F10_S90_L001":"E",
"SNA114916-384W1826-F12_S205_L001":"E",
"SNA114916-384W1826-F6_S46_L001":"E",
"SNA114916-384W1826-F8_S83_L001":"E",
"SNA114916-384W1826-H10_S4_L001":"E",
"SNA114916-384W1826-H12_S207_L001":"E",
"SNA114916-384W1826-H4_S21_L001":"E",
"SNA114916-384W1826-H6_S139_L001":"E",
"SNA114916-384W1826-H8_S41_L001":"E",
"SNA114916-384W1826-J10_S88_L001":"E",
"SNA114916-384W1826-J12_S49_L001":"E",
"SNA114916-384W1826-J4_S18_L001":"E",
"SNA114916-384W1826-J6_S120_L001":"E",
"SNA114916-384W1826-J8_S34_L001":"E",
"SNA114916-384W1826-L10_S151_L001":"E",
"SNA114916-384W1826-L12_S6_L001":"E",
"SNA114916-384W1826-L4_S159_L001":"E",
"SNA114916-384W1826-L6_S12_L001":"E",
"SNA114916-384W1826-L8_S116_L001":"E",
"SNA114916-384W1826-N10_S92_L001":"E",
"SNA114916-384W1826-N12_S191_L001":"E",
"SNA114916-384W1826-N4_S143_L001":"E",
"SNA114916-384W1826-N6_S182_L001":"E",
"SNA114916-384W1826-N8_S29_L001":"E",
"SNA114916-384W1826-P10_S31_L001":"E",
"SNA114916-384W1826-P12_S45_L001":"E",
"SNA114916-384W1826-P4_S50_L001":"E",
"SNA114916-384W1826-P6_S200_L001":"E",
"SNA114916-384W1826-P8_S201_L001":"E",
"SNA114912-384W1773-C21_S187_L001":"A",
"SNA114916-384W1773-G3_S253_L001":"E"
                    },
                "Amp-based-4": {
                        "NIST-A":"A",
                        "NIST-B":"B",
                        "NIST-C":"C",
                        "NIST-D":"D",
                        "NIST-E":"E",
                    },
                "Amp-based-5": {
'"RP019714","G024699","A01"':"A",
'"RP019714","G024700","A02"':"A",
'"RP019714","G024701","A03"':"A",
'"RP019714","G024702","A04"':"A",
'"RP019714","G024703","A05"':"A",
'"RP019714","G024704","A06"':"A",
'"RP019714","G024705","A07"':"A",
'"RP019714","G024706","A08"':"A",
'"RP019714","G024707","A09"':"A",
'"RP019714","G024708","A10"':"A",
'"RP019714","G024709","A11"':"A",
'"RP019714","G024710","A12"':"A",
'"RP019714","G024711","B01"':"A",
'"RP019714","G024712","B02"':"A",
'"RP019714","G024713","B03"':"A",
'"RP019714","G024714","B04"':"A",
'"RP019714","G024715","B05"':"A",
'"RP019714","G024716","B06"':"A",
'"RP019714","G024717","B07"':"A",
'"RP019714","G024718","B08"':"A",
'"RP019714","G024719","B09"':"A",
'"RP019714","G024720","B10"':"A",
'"RP019714","G024721","B11"':"A",
'"RP019714","G024722","B12"':"A",
'"RP019714","G024723","C01"':"A",
'"RP019714","G024725","C02"':"A",
'"RP019714","G024726","C03"':"A",
'"RP019714","G024727","C04"':"A",
'"RP019714","G024728","C05"':"A",
'"RP019714","G024729","C06"':"A",
'"RP019714","G024730","C07"':"A",
'"RP019714","G024731","C08"':"A",
'"RP019714","G024732","C09"':"A",
'"RP019714","G024733","C10"':"A",
'"RP019714","G024734","C11"':"A",
'"RP019714","G024735","C12"':"A",
'"RP019714","G024736","D01"':"A",
'"RP019714","G024737","D02"':"A",
'"RP019714","G026271","D03"':"A",
'"RP019714","G026272","D04"':"A",
'"RP019714","G026273","D05"':"A",
'"RP019714","G026274","D06"':"A",
'"RP019714","G026275","D07"':"A",
'"RP019714","G026276","D08"':"A",
'"RP019714","G024699","E01"':"A",
'"RP019714","G024700","E02"':"A",
'"RP019714","G024701","E03"':"A",
'"RP019714","G024702","E04"':"A",
'"RP019714","G024703","E05"':"A",
'"RP019714","G024704","E06"':"A",
'"RP019714","G024705","E07"':"A",
'"RP019714","G024706","E08"':"A",
'"RP019714","G024707","E09"':"A",
'"RP019714","G024708","E10"':"A",
'"RP019714","G024709","E11"':"A",
'"RP019714","G024710","E12"':"A",
'"RP019714","G024711","F01"':"A",
'"RP019714","G024712","F02"':"A",
'"RP019714","G024713","F03"':"A",
'"RP019714","G024714","F04"':"A",
'"RP019714","G024715","F05"':"A",
'"RP019714","G024716","F06"':"A",
'"RP019714","G024717","F07"':"A",
'"RP019714","G024718","F08"':"A",
'"RP019714","G024719","F09"':"A",
'"RP019714","G024720","F10"':"A",
'"RP019714","G024721","F11"':"A",
'"RP019714","G024722","F12"':"A",
'"RP019714","G024723","G01"':"A",
'"RP019714","G024725","G02"':"A",
'"RP019714","G024726","G03"':"A",
'"RP019714","G024727","G04"':"A",
'"RP019714","G024728","G05"':"A",
'"RP019714","G024729","G06"':"A",
'"RP019714","G024730","G07"':"A",
'"RP019714","G024731","G08"':"A",
'"RP019714","G024732","G09"':"A",
'"RP019714","G024733","G10"':"A",
'"RP019714","G024734","G11"':"A",
'"RP019714","G024735","G12"':"A",
'"RP019714","G024736","H01"':"A",
'"RP019714","G024737","H02"':"A",
'"RP019714","G026271","H03"':"A",
'"RP019714","G026272","H04"':"A",
'"RP019714","G026273","H05"':"A",
'"RP019714","G026274","H06"':"A",
'"RP019714","G026275","H07"':"A",
'"RP019714","G026276","H08"':"A",
'"RP019715","G024699","A01"':"B",
'"RP019715","G024700","A02"':"B",
'"RP019715","G024701","A03"':"B",
'"RP019715","G024702","A04"':"B",
'"RP019715","G024703","A05"':"B",
'"RP019715","G024704","A06"':"B",
'"RP019715","G024705","A07"':"B",
'"RP019715","G024706","A08"':"B",
'"RP019715","G024707","A09"':"B",
'"RP019715","G024708","A10"':"B",
'"RP019715","G024709","A11"':"B",
'"RP019715","G024710","A12"':"B",
'"RP019715","G024711","B01"':"B",
'"RP019715","G024712","B02"':"B",
'"RP019715","G024713","B03"':"B",
'"RP019715","G024714","B04"':"B",
'"RP019715","G024715","B05"':"B",
'"RP019715","G024716","B06"':"B",
'"RP019715","G024717","B07"':"B",
'"RP019715","G024718","B08"':"B",
'"RP019715","G024719","B09"':"B",
'"RP019715","G024720","B10"':"B",
'"RP019715","G024721","B11"':"B",
'"RP019715","G024722","B12"':"B",
'"RP019715","G024723","C01"':"B",
'"RP019715","G024725","C02"':"B",
'"RP019715","G024726","C03"':"B",
'"RP019715","G024727","C04"':"B",
'"RP019715","G024728","C05"':"B",
'"RP019715","G024729","C06"':"B",
'"RP019715","G024730","C07"':"B",
'"RP019715","G024731","C08"':"B",
'"RP019715","G024732","C09"':"B",
'"RP019715","G024733","C10"':"B",
'"RP019715","G024734","C11"':"B",
'"RP019715","G024735","C12"':"B",
'"RP019715","G024736","D01"':"B",
'"RP019715","G024737","D02"':"B",
'"RP019715","G026271","D03"':"B",
'"RP019715","G026272","D04"':"B",
'"RP019715","G026273","D05"':"B",
'"RP019715","G026274","D06"':"B",
'"RP019715","G026275","D07"':"B",
'"RP019715","G026276","D08"':"B",
'"RP019715","G024699","E01"':"B",
'"RP019715","G024700","E02"':"B",
'"RP019715","G024701","E03"':"B",
'"RP019715","G024702","E04"':"B",
'"RP019715","G024703","E05"':"B",
'"RP019715","G024704","E06"':"B",
'"RP019715","G024705","E07"':"B",
'"RP019715","G024706","E08"':"B",
'"RP019715","G024707","E09"':"B",
'"RP019715","G024708","E10"':"B",
'"RP019715","G024709","E11"':"B",
'"RP019715","G024710","E12"':"B",
'"RP019715","G024711","F01"':"B",
'"RP019715","G024712","F02"':"B",
'"RP019715","G024713","F03"':"B",
'"RP019715","G024714","F04"':"B",
'"RP019715","G024715","F05"':"B",
'"RP019715","G024716","F06"':"B",
'"RP019715","G024717","F07"':"B",
'"RP019715","G024718","F08"':"B",
'"RP019715","G024719","F09"':"B",
'"RP019715","G024720","F10"':"B",
'"RP019715","G024721","F11"':"B",
'"RP019715","G024722","F12"':"B",
'"RP019715","G024723","G01"':"B",
'"RP019715","G024725","G02"':"B",
'"RP019715","G024726","G03"':"B",
'"RP019715","G024727","G04"':"B",
'"RP019715","G024728","G05"':"B",
'"RP019715","G024729","G06"':"B",
'"RP019715","G024730","G07"':"B",
'"RP019715","G024731","G08"':"B",
'"RP019715","G024732","G09"':"B",
'"RP019715","G024733","G10"':"B",
'"RP019715","G024734","G11"':"B",
'"RP019715","G024735","G12"':"B",
'"RP019715","G024736","H01"':"B",
'"RP019715","G024737","H02"':"B",
'"RP019715","G026271","H03"':"B",
'"RP019715","G026272","H04"':"B",
'"RP019715","G026273","H05"':"B",
'"RP019715","G026274","H06"':"B",
'"RP019715","G026275","H07"':"B",
'"RP019715","G026276","H08"':"B",
'"RP019716","G024699","A01"':"A",
'"RP019716","G024700","A02"':"A",
'"RP019716","G024701","A03"':"A",
'"RP019716","G024702","A04"':"A",
'"RP019716","G024703","A05"':"A",
'"RP019716","G024704","A06"':"A",
'"RP019716","G024705","A07"':"A",
'"RP019716","G024706","A08"':"A",
'"RP019716","G024707","A09"':"A",
'"RP019716","G024708","A10"':"A",
'"RP019716","G024709","A11"':"A",
'"RP019716","G024710","A12"':"A",
'"RP019716","G024711","B01"':"A",
'"RP019716","G024712","B02"':"A",
'"RP019716","G024713","B03"':"A",
'"RP019716","G024714","B04"':"A",
'"RP019716","G024715","B05"':"A",
'"RP019716","G024716","B06"':"A",
'"RP019716","G024717","B07"':"A",
'"RP019716","G024718","B08"':"A",
'"RP019716","G024719","B09"':"A",
'"RP019716","G024720","B10"':"A",
'"RP019716","G024721","B11"':"A",
'"RP019716","G024722","B12"':"A",
'"RP019716","G024723","C01"':"A",
'"RP019716","G024725","C02"':"A",
'"RP019716","G024726","C03"':"A",
'"RP019716","G024727","C04"':"A",
'"RP019716","G024728","C05"':"A",
'"RP019716","G024729","C06"':"A",
'"RP019716","G024730","C07"':"A",
'"RP019716","G024731","C08"':"A",
'"RP019716","G024732","C09"':"A",
'"RP019716","G024733","C10"':"A",
'"RP019716","G024734","C11"':"A",
'"RP019716","G024735","C12"':"A",
'"RP019716","G024736","D01"':"A",
'"RP019716","G024737","D02"':"A",
'"RP019716","G026271","D03"':"A",
'"RP019716","G026272","D04"':"A",
'"RP019716","G026273","D05"':"A",
'"RP019716","G026274","D06"':"A",
'"RP019716","G026275","D07"':"A",
'"RP019716","G026276","D08"':"A",
'"RP019716","G024699","E01"':"B",
'"RP019716","G024700","E02"':"B",
'"RP019716","G024701","E03"':"B",
'"RP019716","G024702","E04"':"B",
'"RP019716","G024703","E05"':"B",
'"RP019716","G024704","E06"':"B",
'"RP019716","G024705","E07"':"B",
'"RP019716","G024706","E08"':"B",
'"RP019716","G024707","E09"':"B",
'"RP019716","G024708","E10"':"B",
'"RP019716","G024709","E11"':"B",
'"RP019716","G024710","E12"':"B",
'"RP019716","G024711","F01"':"B",
'"RP019716","G024712","F02"':"B",
'"RP019716","G024713","F03"':"B",
'"RP019716","G024714","F04"':"B",
'"RP019716","G024715","F05"':"B",
'"RP019716","G024716","F06"':"B",
'"RP019716","G024717","F07"':"B",
'"RP019716","G024718","F08"':"B",
'"RP019716","G024719","F09"':"B",
'"RP019716","G024720","F10"':"B",
'"RP019716","G024721","F11"':"B",
'"RP019716","G024722","F12"':"B",
'"RP019716","G024723","G01"':"B",
'"RP019716","G024725","G02"':"B",
'"RP019716","G024726","G03"':"B",
'"RP019716","G024727","G04"':"B",
'"RP019716","G024728","G05"':"B",
'"RP019716","G024729","G06"':"B",
'"RP019716","G024730","G07"':"B",
'"RP019716","G024731","G08"':"B",
'"RP019716","G024732","G09"':"B",
'"RP019716","G024733","G10"':"B",
'"RP019716","G024734","G11"':"B",
'"RP019716","G024735","G12"':"B",
'"RP019716","G024736","H01"':"B",
'"RP019716","G024737","H02"':"B",
'"RP019716","G026271","H03"':"B",
'"RP019716","G026272","H04"':"B",
'"RP019716","G026273","H05"':"B",
'"RP019716","G026274","H06"':"B",
'"RP019716","G026275","H07"':"B",
'"RP019716","G026276","H08"':"B",
'"RP019717","G024699","A01"':"C",
'"RP019717","G024700","A02"':"C",
'"RP019717","G024701","A03"':"C",
'"RP019717","G024702","A04"':"C",
'"RP019717","G024703","A05"':"C",
'"RP019717","G024704","A06"':"C",
'"RP019717","G024705","A07"':"C",
'"RP019717","G024706","A08"':"C",
'"RP019717","G024707","A09"':"C",
'"RP019717","G024708","A10"':"C",
'"RP019717","G024709","A11"':"C",
'"RP019717","G024710","A12"':"C",
'"RP019717","G024711","B01"':"C",
'"RP019717","G024712","B02"':"C",
'"RP019717","G024713","B03"':"C",
'"RP019717","G024714","B04"':"C",
'"RP019717","G024715","B05"':"C",
'"RP019717","G024716","B06"':"C",
'"RP019717","G024717","B07"':"C",
'"RP019717","G024718","B08"':"C",
'"RP019717","G024719","B09"':"C",
'"RP019717","G024720","B10"':"C",
'"RP019717","G024721","B11"':"C",
'"RP019717","G024722","B12"':"C",
'"RP019717","G024723","C01"':"C",
'"RP019717","G024725","C02"':"C",
'"RP019717","G024726","C03"':"C",
'"RP019717","G024727","C04"':"C",
'"RP019717","G024728","C05"':"C",
'"RP019717","G024729","C06"':"C",
'"RP019717","G024730","C07"':"C",
'"RP019717","G024731","C08"':"C",
'"RP019717","G024732","C09"':"C",
'"RP019717","G024733","C10"':"C",
'"RP019717","G024734","C11"':"C",
'"RP019717","G024735","C12"':"C",
'"RP019717","G024736","D01"':"C",
'"RP019717","G024737","D02"':"C",
'"RP019717","G026271","D03"':"C",
'"RP019717","G026272","D04"':"C",
'"RP019717","G026273","D05"':"C",
'"RP019717","G026274","D06"':"C",
'"RP019717","G026275","D07"':"C",
'"RP019717","G026276","D08"':"C",
'"RP019717","G024699","E01"':"C",
'"RP019717","G024700","E02"':"C",
'"RP019717","G024701","E03"':"C",
'"RP019717","G024702","E04"':"C",
'"RP019717","G024703","E05"':"C",
'"RP019717","G024704","E06"':"C",
'"RP019717","G024705","E07"':"C",
'"RP019717","G024706","E08"':"C",
'"RP019717","G024707","E09"':"C",
'"RP019717","G024708","E10"':"C",
'"RP019717","G024709","E11"':"C",
'"RP019717","G024710","E12"':"C",
'"RP019717","G024711","F01"':"C",
'"RP019717","G024712","F02"':"C",
'"RP019717","G024713","F03"':"C",
'"RP019717","G024714","F04"':"C",
'"RP019717","G024715","F05"':"C",
'"RP019717","G024716","F06"':"C",
'"RP019717","G024717","F07"':"C",
'"RP019717","G024718","F08"':"C",
'"RP019717","G024719","F09"':"C",
'"RP019717","G024720","F10"':"C",
'"RP019717","G024721","F11"':"C",
'"RP019717","G024722","F12"':"C",
'"RP019717","G024723","G01"':"C",
'"RP019717","G024725","G02"':"C",
'"RP019717","G024726","G03"':"C",
'"RP019717","G024727","G04"':"C",
'"RP019717","G024728","G05"':"C",
'"RP019717","G024729","G06"':"C",
'"RP019717","G024730","G07"':"C",
'"RP019717","G024731","G08"':"C",
'"RP019717","G024732","G09"':"C",
'"RP019717","G024733","G10"':"C",
'"RP019717","G024734","G11"':"C",
'"RP019717","G024735","G12"':"C",
'"RP019717","G024736","H01"':"C",
'"RP019717","G024737","H02"':"C",
'"RP019717","G026271","H03"':"C",
'"RP019717","G026272","H04"':"C",
'"RP019717","G026273","H05"':"C",
'"RP019717","G026274","H06"':"C",
'"RP019717","G026275","H07"':"C",
'"RP019717","G026276","H08"':"C",
'"RP019718","G024699","A01"':"D",
'"RP019718","G024700","A02"':"D",
'"RP019718","G024701","A03"':"D",
'"RP019718","G024702","A04"':"D",
'"RP019718","G024703","A05"':"D",
'"RP019718","G024704","A06"':"D",
'"RP019718","G024705","A07"':"D",
'"RP019718","G024706","A08"':"D",
'"RP019718","G024707","A09"':"D",
'"RP019718","G024708","A10"':"D",
'"RP019718","G024709","A11"':"D",
'"RP019718","G024710","A12"':"D",
'"RP019718","G024711","B01"':"D",
'"RP019718","G024712","B02"':"D",
'"RP019718","G024713","B03"':"D",
'"RP019718","G024714","B04"':"D",
'"RP019718","G024715","B05"':"D",
'"RP019718","G024716","B06"':"D",
'"RP019718","G024717","B07"':"D",
'"RP019718","G024718","B08"':"D",
'"RP019718","G024719","B09"':"D",
'"RP019718","G024720","B10"':"D",
'"RP019718","G024721","B11"':"D",
'"RP019718","G024722","B12"':"D",
'"RP019718","G024723","C01"':"D",
'"RP019718","G024725","C02"':"D",
'"RP019718","G024726","C03"':"D",
'"RP019718","G024727","C04"':"D",
'"RP019718","G024728","C05"':"D",
'"RP019718","G024729","C06"':"D",
'"RP019718","G024730","C07"':"D",
'"RP019718","G024731","C08"':"D",
'"RP019718","G024732","C09"':"D",
'"RP019718","G024733","C10"':"D",
'"RP019718","G024734","C11"':"D",
'"RP019718","G024735","C12"':"D",
'"RP019718","G024736","D01"':"D",
'"RP019718","G024737","D02"':"D",
'"RP019718","G026271","D03"':"D",
'"RP019718","G026272","D04"':"D",
'"RP019718","G026273","D05"':"D",
'"RP019718","G026274","D06"':"D",
'"RP019718","G026275","D07"':"D",
'"RP019718","G026276","D08"':"D",
'"RP019718","G024699","E01"':"D",
'"RP019718","G024700","E02"':"D",
'"RP019718","G024701","E03"':"D",
'"RP019718","G024702","E04"':"D",
'"RP019718","G024703","E05"':"D",
'"RP019718","G024704","E06"':"D",
'"RP019718","G024705","E07"':"D",
'"RP019718","G024706","E08"':"D",
'"RP019718","G024707","E09"':"D",
'"RP019718","G024708","E10"':"D",
'"RP019718","G024709","E11"':"D",
'"RP019718","G024710","E12"':"D",
'"RP019718","G024711","F01"':"D",
'"RP019718","G024712","F02"':"D",
'"RP019718","G024713","F03"':"D",
'"RP019718","G024714","F04"':"D",
'"RP019718","G024715","F05"':"D",
'"RP019718","G024716","F06"':"D",
'"RP019718","G024717","F07"':"D",
'"RP019718","G024718","F08"':"D",
'"RP019718","G024719","F09"':"D",
'"RP019718","G024720","F10"':"D",
'"RP019718","G024721","F11"':"D",
'"RP019718","G024722","F12"':"D",
'"RP019718","G024723","G01"':"D",
'"RP019718","G024725","G02"':"D",
'"RP019718","G024726","G03"':"D",
'"RP019718","G024727","G04"':"D",
'"RP019718","G024728","G05"':"D",
'"RP019718","G024729","G06"':"D",
'"RP019718","G024730","G07"':"D",
'"RP019718","G024731","G08"':"D",
'"RP019718","G024732","G09"':"D",
'"RP019718","G024733","G10"':"D",
'"RP019718","G024734","G11"':"D",
'"RP019718","G024735","G12"':"D",
'"RP019718","G024736","H01"':"D",
'"RP019718","G024737","H02"':"D",
'"RP019718","G026271","H03"':"D",
'"RP019718","G026272","H04"':"D",
'"RP019718","G026273","H05"':"D",
'"RP019718","G026274","H06"':"D",
'"RP019718","G026275","H07"':"D",
'"RP019718","G026276","H08"':"D",
'"RP019719","G024699","A01"':"C",
'"RP019719","G024700","A02"':"C",
'"RP019719","G024701","A03"':"C",
'"RP019719","G024702","A04"':"C",
'"RP019719","G024703","A05"':"C",
'"RP019719","G024704","A06"':"C",
'"RP019719","G024705","A07"':"C",
'"RP019719","G024706","A08"':"C",
'"RP019719","G024707","A09"':"C",
'"RP019719","G024708","A10"':"C",
'"RP019719","G024709","A11"':"C",
'"RP019719","G024710","A12"':"C",
'"RP019719","G024711","B01"':"C",
'"RP019719","G024712","B02"':"C",
'"RP019719","G024713","B03"':"C",
'"RP019719","G024714","B04"':"C",
'"RP019719","G024715","B05"':"C",
'"RP019719","G024716","B06"':"C",
'"RP019719","G024717","B07"':"C",
'"RP019719","G024718","B08"':"C",
'"RP019719","G024719","B09"':"C",
'"RP019719","G024720","B10"':"C",
'"RP019719","G024721","B11"':"C",
'"RP019719","G024722","B12"':"C",
'"RP019719","G024723","C01"':"C",
'"RP019719","G024725","C02"':"C",
'"RP019719","G024726","C03"':"C",
'"RP019719","G024727","C04"':"C",
'"RP019719","G024728","C05"':"C",
'"RP019719","G024729","C06"':"C",
'"RP019719","G024730","C07"':"C",
'"RP019719","G024731","C08"':"C",
'"RP019719","G024732","C09"':"C",
'"RP019719","G024733","C10"':"C",
'"RP019719","G024734","C11"':"C",
'"RP019719","G024735","C12"':"C",
'"RP019719","G024736","D01"':"C",
'"RP019719","G024737","D02"':"C",
'"RP019719","G026271","D03"':"C",
'"RP019719","G026272","D04"':"C",
'"RP019719","G026273","D05"':"C",
'"RP019719","G026274","D06"':"C",
'"RP019719","G026275","D07"':"C",
'"RP019719","G026276","D08"':"C",
'"RP019719","G024699","E01"':"D",
'"RP019719","G024700","E02"':"D",
'"RP019719","G024701","E03"':"D",
'"RP019719","G024702","E04"':"D",
'"RP019719","G024703","E05"':"D",
'"RP019719","G024704","E06"':"D",
'"RP019719","G024705","E07"':"D",
'"RP019719","G024706","E08"':"D",
'"RP019719","G024707","E09"':"D",
'"RP019719","G024708","E10"':"D",
'"RP019719","G024709","E11"':"D",
'"RP019719","G024710","E12"':"D",
'"RP019719","G024711","F01"':"D",
'"RP019719","G024712","F02"':"D",
'"RP019719","G024713","F03"':"D",
'"RP019719","G024714","F04"':"D",
'"RP019719","G024715","F05"':"D",
'"RP019719","G024716","F06"':"D",
'"RP019719","G024717","F07"':"D",
'"RP019719","G024718","F08"':"D",
'"RP019719","G024719","F09"':"D",
'"RP019719","G024720","F10"':"D",
'"RP019719","G024721","F11"':"D",
'"RP019719","G024722","F12"':"D",
'"RP019719","G024723","G01"':"D",
'"RP019719","G024725","G02"':"D",
'"RP019719","G024726","G03"':"D",
'"RP019719","G024727","G04"':"D",
'"RP019719","G024728","G05"':"D",
'"RP019719","G024729","G06"':"D",
'"RP019719","G024730","G07"':"D",
'"RP019719","G024731","G08"':"D",
'"RP019719","G024732","G09"':"D",
'"RP019719","G024733","G10"':"D",
'"RP019719","G024734","G11"':"D",
'"RP019719","G024735","G12"':"D",
'"RP019719","G024736","H01"':"D",
'"RP019719","G024737","H02"':"D",
'"RP019719","G026271","H03"':"D",
'"RP019719","G026272","H04"':"D",
'"RP019719","G026273","H05"':"D",
'"RP019719","G026274","H06"':"D",
'"RP019719","G026275","H07"':"D",
'"RP019719","G026276","H08"':"D",
'"RP019720","G024699","A01"':"E",
'"RP019720","G024700","A02"':"E",
'"RP019720","G024701","A03"':"E",
'"RP019720","G024702","A04"':"E",
'"RP019720","G024703","A05"':"E",
'"RP019720","G024704","A06"':"E",
'"RP019720","G024705","A07"':"E",
'"RP019720","G024706","A08"':"E",
'"RP019720","G024707","A09"':"E",
'"RP019720","G024708","A10"':"E",
'"RP019720","G024709","A11"':"E",
'"RP019720","G024710","A12"':"E",
'"RP019720","G024711","B01"':"E",
'"RP019720","G024712","B02"':"E",
'"RP019720","G024713","B03"':"E",
'"RP019720","G024714","B04"':"E",
'"RP019720","G024715","B05"':"E",
'"RP019720","G024716","B06"':"E",
'"RP019720","G024717","B07"':"E",
'"RP019720","G024718","B08"':"E",
'"RP019720","G024719","B09"':"E",
'"RP019720","G024720","B10"':"E",
'"RP019720","G024721","B11"':"E",
'"RP019720","G024722","B12"':"E",
'"RP019720","G024723","C01"':"E",
'"RP019720","G024725","C02"':"E",
'"RP019720","G024726","C03"':"E",
'"RP019720","G024727","C04"':"E",
'"RP019720","G024728","C05"':"E",
'"RP019720","G024729","C06"':"E",
'"RP019720","G024730","C07"':"E",
'"RP019720","G024731","C08"':"E",
'"RP019720","G024732","C09"':"E",
'"RP019720","G024733","C10"':"E",
'"RP019720","G024734","C11"':"E",
'"RP019720","G024735","C12"':"E",
'"RP019720","G024736","D01"':"E",
'"RP019720","G024737","D02"':"E",
'"RP019720","G026271","D03"':"E",
'"RP019720","G026272","D04"':"E",
'"RP019720","G026273","D05"':"E",
'"RP019720","G026274","D06"':"E",
'"RP019720","G026275","D07"':"E",
'"RP019720","G026276","D08"':"E",
'"RP019720","G024699","E01"':"E",
'"RP019720","G024700","E02"':"E",
'"RP019720","G024701","E03"':"E",
'"RP019720","G024702","E04"':"E",
'"RP019720","G024703","E05"':"E",
'"RP019720","G024704","E06"':"E",
'"RP019720","G024705","E07"':"E",
'"RP019720","G024706","E08"':"E",
'"RP019720","G024707","E09"':"E",
'"RP019720","G024708","E10"':"E",
'"RP019720","G024709","E11"':"E",
'"RP019720","G024710","E12"':"E",
'"RP019720","G024711","F01"':"E",
'"RP019720","G024712","F02"':"E",
'"RP019720","G024713","F03"':"E",
'"RP019720","G024714","F04"':"E",
'"RP019720","G024715","F05"':"E",
'"RP019720","G024716","F06"':"E",
'"RP019720","G024717","F07"':"E",
'"RP019720","G024718","F08"':"E",
'"RP019720","G024719","F09"':"E",
'"RP019720","G024720","F10"':"E",
'"RP019720","G024721","F11"':"E",
'"RP019720","G024722","F12"':"E",
'"RP019720","G024723","G01"':"E",
'"RP019720","G024725","G02"':"E",
'"RP019720","G024726","G03"':"E",
'"RP019720","G024727","G04"':"E",
'"RP019720","G024728","G05"':"E",
'"RP019720","G024729","G06"':"E",
'"RP019720","G024730","G07"':"E",
'"RP019720","G024731","G08"':"E",
'"RP019720","G024732","G09"':"E",
'"RP019720","G024733","G10"':"E",
'"RP019720","G024734","G11"':"E",
'"RP019720","G024735","G12"':"E",
'"RP019720","G024736","H01"':"E",
'"RP019720","G024737","H02"':"E",
'"RP019720","G026271","H03"':"E",
'"RP019720","G026272","H04"':"E",
'"RP019720","G026273","H05"':"E",
'"RP019720","G026274","H06"':"E",
'"RP019720","G026275","H07"':"E",
'"RP019720","G026276","H08"':"E",
'"RP019721","G024699","A01"':"E",
'"RP019721","G024700","A02"':"E",
'"RP019721","G024701","A03"':"E",
'"RP019721","G024702","A04"':"E",
'"RP019721","G024703","A05"':"E",
'"RP019721","G024704","A06"':"E",
'"RP019721","G024705","A07"':"E",
'"RP019721","G024706","A08"':"E",
'"RP019721","G024707","A09"':"E",
'"RP019721","G024708","A10"':"E",
'"RP019721","G024709","A11"':"E",
'"RP019721","G024710","A12"':"E",
'"RP019721","G024711","B01"':"E",
'"RP019721","G024712","B02"':"E",
'"RP019721","G024713","B03"':"E",
'"RP019721","G024714","B04"':"E",
'"RP019721","G024715","B05"':"E",
'"RP019721","G024716","B06"':"E",
'"RP019721","G024717","B07"':"E",
'"RP019721","G024718","B08"':"E",
'"RP019721","G024719","B09"':"E",
'"RP019721","G024720","B10"':"E",
'"RP019721","G024721","B11"':"E",
'"RP019721","G024722","B12"':"E",
'"RP019721","G024723","C01"':"E",
'"RP019721","G024725","C02"':"E",
'"RP019721","G024726","C03"':"E",
'"RP019721","G024727","C04"':"E",
'"RP019721","G024728","C05"':"E",
'"RP019721","G024729","C06"':"E",
'"RP019721","G024730","C07"':"E",
'"RP019721","G024731","C08"':"E",
'"RP019721","G024732","C09"':"E",
'"RP019721","G024733","C10"':"E",
'"RP019721","G024734","C11"':"E",
'"RP019721","G024735","C12"':"E",
'"RP019721","G024736","D01"':"E",
'"RP019721","G024737","D02"':"E",
'"RP019721","G026271","D03"':"E",
'"RP019721","G026272","D04"':"E",
'"RP019721","G026273","D05"':"E",
'"RP019721","G026274","D06"':"E",
'"RP019721","G026275","D07"':"E",
'"RP019721","G026276","D08"':"E"
                    },
                "rhAmpSeq-1": {
                    "AGGTAAGG_GGTCCAGA":"C",
                    "AGGTAAGG_GTATAACA":"D",
                    "AGGTAAGG_AACTTGAC":"B",
                    "AGGTAAGG_TCGGAATG":"D",
                    "AGGTAAGG_TTCGCTGA":"E",
                    "AGGTAAGG_CACATCCT":"C",
                    "CCAACATT_GGTCCAGA":"A",
                    "AGGTAAGG_ACACGATC":"B",
                    "CCAACATT_ACACGATC":"A",
                    "AGGTAAGG_AACGCATT":"E"
                    }
            }
    filetracker = {}
    for l in data:
        successfully_parsed = False
        dataset = {}
        #Datasets
        dataset_id = collections[collection_id]
        for d in [l["InstitutionName"]]:
            dataset_id += "/"+d
            modified_l = l.copy()

            modified_l["id"] = dataset_id
            modified_l["DatasetName"] = d
            modified_l["CollectionId"] = collections[collection_id]
            #print "modified_l"
            #print modified_l
            #String replace invalid characters
            for k, v in modified_l.iteritems():
                if v is None:
                    v = ""
                #print "k"
                #print k
                #print v
                modified_l[k] = str(v)

            dataasets[dataset_id] = modified_l

        
        folder = l["FolderName"]
        tracker = False
        cert_files = os.walk("/Users/Programmer/Documents/Projects/Labcas/labcas-data/NIST/Anonymous-Participants/")
        for ext in cert_files:  #Bionano
            directory, midpath, filen = ext
            #print "directory"
            #print directory
            #print len(filen)
            if len(filen) == 0:
                continue
            comp_dir = directory.replace("/Users/Programmer/Documents/Projects/Labcas/labcas-data/NIST/Anonymous-Participants/","")
            if comp_dir.split("/") > 1:
                comp_dir = comp_dir.split("/")[0]
            #print comp_dir
            for filenn in filen:
                if "NIST-E" in filenn and comp_dir == l["FolderName"]:
                    print ("AMP4")
                    print (filenn)
                if filenn not in filetracker:
                    filetracker[filenn] = False
                if comp_dir in folderRegMap:
                    cont_flag = False
                    #print filenn
                    #print comp_dir
                    #print l["FolderName"]
                    if folderRegMap[comp_dir] and comp_dir != "Amp-based-5" and comp_dir == l["FolderName"]:
                        #if "G026273_RP019719" in filenn:
                        #    print "cont1"
                        #    print filenn
                        #    tracker = True
                        for k in folderRegMap[comp_dir].keys():
                            print (k)
                            if k in filenn and folderRegMap[comp_dir][k] == l["SampleID"]:
                                cont_flag = True
                                #if "G026273_RP019719" in filenn:
                                #    print "HERE"
                                #    print folderRegMap[comp_dir][l["SampleID"]]

                        #if folderRegMap[comp_dir][l["SampleID"]] in filenn:
                        #    cont_flag = True

                        #if tracker and "G026273_RP019719" not in filenn:
                        #    print "map"
                        #    print folderRegMap[comp_dir][l["SampleID"]]
                        #    tracker = False
                    elif folderRegMap[comp_dir] and comp_dir == "Amp-based-5" and comp_dir == l["FolderName"]:
                        #if "G026273_RP019719" in filenn:
                        #    print "cont2"
                        #    print filenn
                        for k in folderRegMap[comp_dir].keys():
                            k_split = [item.replace('"',"") for item in k.split(",")]
                            if k_split[0] in filenn and k_split[1] in filenn and k_split[2] in filenn and folderRegMap[comp_dir][k] == l["SampleID"]:
                                cont_flag = True
                                break
                            #if "RP019719" in k and "G024704" in k and "A06" in k and  "RP019719" in filenn and "G024704" in filenn and "A06" in filenn and folderRegMap[comp_dir][k] == l["SampleID"]:
                            #    print  k_split[0] in filenn and k_split[1] in filenn and k_split[2] in filenn
                            #    print "k_split1"
                            #    print k_split
                                #sys.exit()
                            #if k_split[0] == "RP019719" and k_split[1] == "G026273" and k_split[2] == "H05":
                            #    print "Matched"
                            #    print folderRegMap[comp_dir][k]
                            #    break

                    #if "G026273_RP019719" in filenn and l["FolderName"] == "Amp-based-5" and l["SampleID"] == "D":
                    #    print "HERE0"
                    #    print comp_dir
                    #    print l["SampleID"]
                    #    print l["FolderName"]
                    #    if comp_dir == l["FolderName"]:
                    #        print cont_flag
                    #        print filenn
                    #    sys.exit()

                    if not cont_flag:
                        continue
                    print ("pass")
                    filetracker[filenn] = True

                    #Files
                    file_id = "/".join([collections[collection_id],l["InstitutionName"],l["Instrument"],l["SourceMaterial"],filenn])

                    #print file_id
                    dataset_id = "/".join([collections[collection_id],l["InstitutionName"]])

                    #print dataset_id

                    #if "G026273_RP019719" in filenn:
                    #    print "HERE2"
                    #    print l["SampleID"]
                    #    sys.exit()
                    modified_l = l.copy()

                    modified_l["id"] = file_id
                    modified_l["file_id"] = file_id
                    modified_l["FileName"] = filenn #Bionano
                    modified_l["FileType"] = [filenn.split(".")]
                    modified_l["DatasetId"] = dataset_id
                    modified_l["DatasetName"] = l["FolderName"]
                    modified_l["CollectionId"] = collections[collection_id]

                    #String replace invalid characters
                    for k, v in modified_l.iteritems():
                        if v is None:
                            v = ""
                        modified_l[k] = str(v)

                    files.append(modified_l)

    #for k in filetracker:
    #    if not filetracker[k]:
    #        print k

    #sys.exit()
    with open(collections[collection_id]+"-datasets.txt", "wb") as d_inp:
        #print list(dataasets.values())
        d_inp.write(json.dumps(list(dataasets.values())))

    with open(collections[collection_id]+"-files.txt", "wb") as f_inp:
        f_inp.write(json.dumps(files))

    return files

def genome_parser_cobo():

    
    #Genome editing - choose one of the below to parse, not both
    file = "/Users/Programmer/Documents/Projects/NIST/NIST_data/Genome Editing Collection/File_SeqExtension_cobo.xlsx"
    sheet = "Sheet1"

    excel_data_df = pandas.read_excel(file, sheet_name=sheet)

    result = excel_data_df.to_json(orient="records")
    data = json.loads(result)
    # print whole sheet data

    collections = ["fcs_interlab_study","Genomics_Editing_Consortium","cell_line_provenance"]
    collection_id = 1

    count = 0

    dataasets = {}
    files = []

    for l in data:
        dataset = {}
        #Datasets
        dataset_id = collections[collection_id]
        for d in [l["InstitutionName"]]:
            dataset_id += "/"+d
            modified_l = l.copy()

            modified_l["id"] = dataset_id
            modified_l["DatasetName"] = d
            modified_l["CollectionId"] = collections[collection_id]

            #String replace invalid characters
            for k, v in modified_l.iteritems():
                if v is None:
                    v = ""

                modified_l[k] = str(v)

            dataasets[dataset_id] = modified_l

        
        fcomp = [l["FileName"],""]


        if "*" in l["FileName"]:
            fcomp = l["FileName"].split("*")

        print (fcomp)
        
        cert_files = os.walk("/Users/Programmer/Documents/Projects/Labcas/labcas-data/NIST/COBO")
        for ext in cert_files:  #Bionano
            directory, midpath, filen = ext

            if len(filen) == 0:
                continue
            
            for filenn in filen:
                #J5_*.fsa the 5 compared to fcomp[1] which is 5 from *5*.fsa, fcomp[2] is .fsa
                if "*" in l["FileName"] and  filenn[1] == fcomp[1] and filenn.endswith(fcomp[2]):
                    filen_split = filenn.split(".", 1)
                    #Files
                    file_id = "/".join([collections[collection_id],l["InstitutionName"],l["Instrument"],l["SourceMaterial"],filenn])

                    print (file_id)

                    dataset_id = "/".join([collections[collection_id],l["InstitutionName"]])
                    modified_l = l.copy()

                    modified_l["id"] = file_id
                    modified_l["file_id"] = file_id
                    modified_l["FileName"] = filenn #Bionano
                    modified_l["FileType"] = [filen_split[1]]
                    modified_l["DatasetId"] = dataset_id
                    modified_l["CollectionId"] = collections[collection_id]

                    #String replace invalid characters
                    for k, v in modified_l.iteritems():
                        if v is None:
                            v = ""
                        modified_l[k] = str(v)

                    files.append(modified_l)


    with open(collections[collection_id]+"-datasets.txt", "wb") as d_inp:
        #print list(dataasets.values())
        d_inp.write(json.dumps(list(dataasets.values())))

    with open(collections[collection_id]+"-files.txt", "wb") as f_inp:
        f_inp.write(json.dumps(files))

    return files

    
def genome_parser_twin():
    #Genome editing - choose one of the below to parse, not both
    file = "/Users/Programmer/Documents/Projects/NIST/NIST_data/Genome Editing Collection/File_SeqExtension_TwinstrandDNA-blinded.xlsx"
    #file = "/Users/Programmer/Documents/Projects/NIST/NIST_data/Genome Editing Collection/File_SeqExtension_TwinstrandDNA-unblinded.xlsx"
    sheet = "Experimental_Details"

    excel_data_df = pandas.read_excel(file, sheet_name=sheet)

    result = excel_data_df.to_json(orient="records")
    data = json.loads(result)
    # print whole sheet data

    collections = ["fcs_interlab_study","Genomics_Editing_Consortium","cell_line_provenance"]
    collection_id = 1

    count = 0

    dataasets = {}
    files = []

    for l in data:
        dataset = {}
        if l["Sample"]: #TwinStrand
        #if l["Sample"]: #Bionano
            count += 1


            #Datasets
            dataset_id = collections[collection_id]
            for d in [l["Institution"]]:
                #print l["Institution"]
                dataset_id += "/"+d
                modified_l = l.copy()

                modified_l["id"] = dataset_id
                modified_l["DatasetName"] = d
                modified_l["CollectionId"] = collections[collection_id]

                #String replace invalid characters
                for k, v in modified_l.iteritems():
                    if v is None:
                        v = ""

                    modified_l[k] = str(v)

                dataasets[dataset_id] = modified_l

            #processedlevel + associated file extension
            for ext in [["raw","R1.fq.gz"],["raw","R2.fq.gz"],["processed","bai"],["processed","bam"]]: #TwinStrand
            #for ext in [["raw","bnx.gz"],["processed","zip"]]:  #Bionano
                

                #Files

                new_fileid_list = []
                for val in l.values():
                    if type(val) == int or type(val) == float:
                        new_fileid_list.append(replaceMultiple(str(val), replaced_chars, "_"))
                    elif val is None:
                        new_fileid_list.append("None")
                    else:
                        new_fileid_list.append(replaceMultiple(val.encode('ascii', errors='ignore').decode(), replaced_chars, "_"))
                file_id = "/".join([collections[collection_id]]+new_fileid_list)
                print (file_id)

                dataset_id = "/".join([collections[collection_id],l["Institution"]])
                modified_l = l.copy()

                modified_l["id"] = file_id+"."+ext[1]
                modified_l["file_id"] = file_id
                modified_l["ProcessingLevel"] = ext[0]
                #modified_l["FileName"] = l["Sample"]+"."+ext[1] #Bionano
                modified_l["FileName"] = l["Sample"]+"."+ext[1] #TwinStrand
                modified_l["FileType"] = [ext[1]]
                modified_l["DatasetId"] = dataset_id
                modified_l["CollectionId"] = collections[collection_id]

                #String replace invalid characters
                for k, v in modified_l.iteritems():
                    if v is None:
                        v = ""
                    modified_l[k] = str(v)

                files.append(modified_l)


    with open(collections[collection_id]+"-datasets.txt", "wb") as d_inp:
        #print list(dataasets.values())
        d_inp.write(json.dumps(list(dataasets.values())))

    with open(collections[collection_id]+"-files.txt", "wb") as f_inp:
        f_inp.write(json.dumps(files))

    return files

#generate_metadata(genome_parser_twin(), root_metadata_path, "Genomics_Editing_Consortium")
#generate_metadata(genome_parser_cert(), root_metadata_path, "Genomics_Editing_Consortium")
#generate_metadata(genome_parser_bion(), root_metadata_path, "Genomics_Editing_Consortium")
#generate_metadata(genome_parser_cobo(), root_metadata_path, "Genomics_Editing_Consortium")
#generate_metadata(genome_parser_anon(), root_metadata_path, "Genomics_Editing_Consortium")
# Note: Legacy self-invocation disabled. Use CLI entrypoint above instead.
# generate_metadata(genome_parser_mission(), root_metadata_path, "Genomics_Editing_Consortium")
# generate_metadata(cell_provenance(), root_metadata_path, "cell_line_provenance")
# generate_metadata(flow_cyt_parser(), root_metadata_path, "fcs_interlab_study")
