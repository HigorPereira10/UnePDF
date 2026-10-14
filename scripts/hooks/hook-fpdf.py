# Também LGPL: módulos como .py soltos, pelo mesmo motivo do hook da brazilfiscalreport.
from PyInstaller.utils.hooks import collect_data_files

datas = collect_data_files("fpdf")
module_collection_mode = "py"
